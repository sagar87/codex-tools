from typing import List, Optional, Union

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from ..base_logger import logger
from ..constants import Attrs, Dims, Features, Layers, Props
from .utils import (
    _autocrop,
    _colorize,
    _get_listed_colormap,
    _label_segmentation_mask,
    _render_labels,
    _render_segmentation,
)


@xr.register_dataset_accessor("pl")
class PlotAccessor:
    """Adds plotting functions to the image container."""

    def __init__(self, xarray_obj):
        self._obj = xarray_obj

    def _get_bounds(self):
        """
        Get the bounds of the object.

        Returns
        -------
        list
            A list containing the minimum and maximum values for the x and y coordinates.
        """
        xmin = self._obj.coords[Dims.X].values[0]
        ymin = self._obj.coords[Dims.Y].values[0]
        xmax = self._obj.coords[Dims.X].values[-1]
        ymax = self._obj.coords[Dims.Y].values[-1]

        return [xmin, xmax, ymin, ymax]

    def _create_channel_legend(self, **kwargs):
        """
        Create a legend for the channels in the plot layer. Used when rendering intensities.

        Returns:
            elements (list): A list of Patch objects representing the legend elements.
        """
        # checking if the plot layer exists
        assert Layers.PLOT in self._obj, "No plot layer found. Please call pl.colorize() first."
        # checking if the image colors attribute exists
        assert (
            Attrs.IMAGE_COLORS in self._obj[Layers.PLOT].attrs
        ), "No image colors found. Please call pl.colorize() first."

        color_dict = self._obj[Layers.PLOT].attrs[Attrs.IMAGE_COLORS]

        # removing unlabeled cells (label = 0)
        color_dict = {k: v for k, v in color_dict.items() if k != 0}

        elements = [Patch(facecolor=c, label=ch, **kwargs) for ch, c in color_dict.items()]
        return elements

    def _create_segmentation_legend(self):
        """
        Create a legend for the segmentation layers.

        Returns:
            elements (list): A list of Line2D objects representing the segmentation layers.
        """
        assert (
            Attrs.SEGMENTATION_COLORS in self._obj[Layers.PLOT].attrs
        ), "No segmentation colors found. Please specify colors when rendering multiple segmentation masks."

        color_dict = self._obj[Layers.PLOT].attrs[Attrs.SEGMENTATION_COLORS]

        elements = [
            Line2D(
                [0],
                [0],
                color=c,
                label=ch,
            )
            for ch, c in color_dict.items()
        ]

        return elements

    def _create_label_legend(self):
        """
        Create a legend for the cell type labels.

        Returns:
            elements (list): A list of Line2D objects representing the legend elements.
        """
        # getting colors and names for each cell type label
        color_dict = self._obj.la._label_to_dict(Props.COLOR)
        names_dict = self._obj.la._label_to_dict(Props.NAME)

        # removing unlabeled cells (label = 0)
        color_dict = {k: v for k, v in color_dict.items() if k != 0}
        names_dict = {k: v for k, v in names_dict.items() if k != 0}

        elements = [
            Line2D(
                [0],
                [0],
                marker="o",
                color="w",
                label=names_dict[i],
                markerfacecolor=color_dict[i],
                markersize=15,
            )
            for i in sorted(color_dict)
            if i in self._obj.coords[Dims.LABELS]
        ]

        return elements

    def colorize(
        self,
        colors: List[str] = [
            "#e6194B",
            "#3cb44b",
            "#ffe119",
            "#4363d8",
            "#f58231",
            "#911eb4",
            "#42d4f4",
            "#f032e6",
            "#bfef45",
            "#fabed4",
            "#469990",
            "#dcbeff",
            "#9A6324",
            "#fffac8",
            "#800000",
            "#aaffc3",
            "#808000",
            "#ffd8b1",
            "#000075",
            "#a9a9a9",
        ],
        background: str = "black",
        normalize: bool = True,
        merge: bool = True,
    ) -> xr.Dataset:
        """
        Colorizes a stack of images.

        Parameters
        ----------
        colors : List[str], optional
            A list of strings that denote the color of each channel. Default is ["C0", "C1", "C2", "C3"].
        background : str, optional
            Background color of the colorized image. Default is "black".
        normalize : bool, optional
            Normalize the image prior to colorizing it. Default is True.
        merge : True, optional
            Merge the channel dimension. Default is True.

        Returns
        -------
        xr.Dataset
            The image container with the colorized image stored in Layers.PLOT.

        Example Usage
        --------------
        >>> ds.pp['PAX5', 'CD3'].pl.colorize(['red', 'green']).pl.show()
        """
        # check if a plot already exists
        assert (
            Layers.PLOT not in self._obj
        ), "A plot layer already exists. If you want to plot the channel intensities and a segmentation mask, make sure to call pl.colorize() first, and then pl.render_segmentation() to render the segmentation on top of it. Alternatively, you can call pl.imshow(render_segmentation=True) to achieve the same effect."

        if isinstance(colors, str):
            colors = [colors]

        image_layer = self._obj[Layers.IMAGE]
        colored = _colorize(
            image_layer.values,
            colors=colors,
            background=background,
            normalize=normalize,
        )

        da = xr.DataArray(
            colored,
            coords=[
                image_layer.coords[Dims.CHANNELS],
                image_layer.coords[Dims.Y],
                image_layer.coords[Dims.X],
                ["r", "g", "b", "a"],
            ],
            dims=[Dims.CHANNELS, Dims.Y, Dims.X, Dims.RGBA],
            name=Layers.PLOT,
            attrs={Attrs.IMAGE_COLORS: {k.item(): v for k, v in zip(image_layer.coords[Dims.CHANNELS], colors)}},
        )

        if merge:
            da = da.sum(Dims.CHANNELS, keep_attrs=True)
            da.values[da.values > 1] = 1.0

        return xr.merge([self._obj, da])

    def show(
        self,
        render_image: bool = True,
        render_segmentation: bool = False,
        render_labels: bool = False,
        ax=None,
        legend_image: bool = True,
        legend_segmentation: bool = True,
        legend_label: bool = True,
        downsample: int = 1,
        legend_kwargs: dict = {"framealpha": 1},
        segmentation_kwargs: dict = {},
        label_kwargs: dict = {},
    ) -> xr.Dataset:
        """
        Display an image with optional rendering elements. Can be used to render intensities, segmentation masks and labels, either individually or all at once.

        Parameters:
        - render_image (bool): Whether to render the image with channel intensities. Default is True.
        - render_segmentation (bool): Whether to render segmentation. Default is False.
        - render_labels (bool): Whether to render labels. Default is False.
        - ax: The matplotlib axes to plot on. If None, the current axes will be used.
        - legend_image (bool): Whether to show the channel legend. Default is True.
        - legend_segmentation (bool): Whether to show the segmentation legend (only becomes relevant when dealing with multiple segmentation layers, e. g. when using cellpose). Default is False.
        - legend_label (bool): Whether to show the label legend. Default is True.
        - downsample (int): Downsample factor for the image. Default is 1 (no downsampling).
        - legend_kwargs (dict): Keyword arguments for configuring the legend. Default is {"framealpha": 1}.
        - segmentation_kwargs (dict): Keyword arguments for rendering the segmentation. Default is {}.
        - label_kwargs (dict): Keyword arguments for rendering the labels. Default is {}.

        Returns:
        - obj (xr.Dataset): The modified dataset object.

        Raises:
        - AssertionError: If no rendering element is specified.

        Note:
        - This method displays an image with optional rendering elements such as intensities, labels, and segmentation.
        - The `render_intensities`, `render_labels`, and `render_segmentation` parameters control which rendering elements are displayed.
        - The `ax` parameter allows specifying a specific matplotlib axes to plot on. If None, the current axes will be used.
        - The `show_channel_legend` and `show_label_legend` parameters control whether to show the channel and label legends, respectively.
        - The `legend_kwargs`, `segmentation_kwargs`, and `label_kwargs` parameters allow configuring the appearance of the legend, segmentation, and labels, respectively.
        """
        # check that at least one rendering element is specified
        assert any(
            [render_image, render_labels, render_segmentation]
        ), "No rendering element specified. Please set at least one of 'render_image', 'render_labels', or 'render_segmentation' to True."

        # copying the input object to avoid colorizing the original object in place
        obj = self._obj.copy()
        if Layers.PLOT not in self._obj and render_image:
            # if there are more than 20 channels, only the first one is plotted
            if self._obj.sizes[Dims.CHANNELS] > 20:
                logger.warning(
                    "More than 20 channels are present in the image. Plotting first channel only. You can subset the channels via pp.[['channel1', 'channel2', ...]] or specify your own color scheme by calling pp.colorize() before calling pl.show()."
                )
                channel = str(self._obj.coords[Dims.CHANNELS].values[0])
                obj = self._obj.pp[channel].pl.colorize(colors=["white"])
            # if there are less than 20 channels, all are plotted
            else:
                obj = self._obj.pl.colorize()

        if render_labels:
            obj = obj.pl.render_labels(**label_kwargs)

        if render_segmentation:
            obj = obj.pl.render_segmentation(**segmentation_kwargs)
            # it should not be possible to show a segmentation legend if there is only one segmentation layer
            segmentation_shape = self._obj[segmentation_kwargs.get("layer_key", Layers.SEGMENTATION)].values.shape
            legend_segmentation = legend_segmentation and len(segmentation_shape) > 2

        legend_image = legend_image and render_image
        legend_segmentation = legend_segmentation and render_segmentation
        legend_label = legend_label and render_labels

        return obj.pl.imshow(
            legend_image=legend_image,
            legend_segmentation=legend_segmentation,
            legend_label=legend_label,
            ax=ax,
            downsample=downsample,
            legend_kwargs=legend_kwargs,
            segmentation_kwargs=segmentation_kwargs,
        )

    def annotate(
        self,
        variable: str = "cell",
        layer_key: str = Layers.OBS,
        highlight: list = [],
        text_kwargs: dict = {"color": "w", "fontsize": 12},
        highlight_kwargs: dict = {"color": "w", "fontsize": 16, "fontweight": "bold"},
        bbox: Union[List, None] = None,
        format_string: str = "",
        ax=None,
    ) -> xr.Dataset:
        """
        Annotates cells with their respective number on the plot.

        Parameters
        ----------
        variable : str, optional
            The feature in the observation table to be used for cell annotation. Default is "cell".
        layer_key : str, optional
            The key representing the layer in the data object. Default is Layers.OBS.
        highlight : list, optional
            A list containing cell IDs to be highlighted in the plot.
        text_kwargs : dict, optional
            Keyword arguments passed to matplotlib's text function for normal cell annotations.
        highlight_kwargs : dict, optional
            Similar to 'text_kwargs' but specifically for the cell IDs passed via 'highlight'.
        bbox : Union[List, None], optional
            A list containing bounding box coordinates [xmin, xmax, ymin, ymax] to annotate cells only within the box.
            Default is None, which annotates all cells.
        format_string : str, optional
            The format string used to format the cell annotation text. Default is "" (no formatting).
        ax : matplotlib.axes, optional
            The matplotlib axis to plot on. If not provided, the current axis will be used.

        Returns
        -------
        xr.Dataset
            The updated image container.

        Notes
        -----
        - The function annotates cells with their respective values from the selected feature.
        - You can highlight specific cells in the plot using the 'highlight' parameter.
        - Bounding box coordinates can be provided via 'bbox' to annotate cells only within the specified box.
        - 'format_string' can be used to format the cell annotation text (e.g., "{t:.2f}" for float formatting).
        """
        if ax is None:
            ax = plt.gca()

        if bbox is None:
            cells = self._obj.coords[Dims.CELLS]
        else:
            assert len(bbox) == 4, "The bbox-argument must specify [xmin, xmax, ymin, ymax]."
            sub = self._obj.im[bbox[0] : bbox[1], bbox[2] : bbox[3]]
            cells = sub.coords[Dims.CELLS]

        for cell in cells:
            x = self._obj[Layers.OBS].sel({Dims.CELLS: cell, Dims.FEATURES: Features.X}).values
            y = self._obj[Layers.OBS].sel({Dims.CELLS: cell, Dims.FEATURES: Features.Y}).values
            if variable != "cell":
                table = self._obj[layer_key]
                dims = table.sizes
                if len(dims) != 2:
                    raise ValueError("Layer does not have the dimension.")
                if Dims.CELLS not in dims:
                    raise ValueError("Layer does not have a cell dimension.")

                dim = [d for d in dims if d != Dims.CELLS][0]

                t = table.sel({Dims.CELLS: cell, dim: variable}).values
            else:
                t = cell.values

            if cell in highlight:
                ax.text(x, y, s=f"{t:{format_string}}", **highlight_kwargs)
            else:

                ax.text(x, y, s=f"{t:{format_string}}", **text_kwargs)

        return self._obj

    def render_segmentation(
        self,
        layer_key: str = Layers.SEGMENTATION,
        colors: List[str] = [
            "white",
            "#e6194B",
            "#3cb44b",
            "#ffe119",
            "#4363d8",
            "#f58231",
            "#911eb4",
            "#42d4f4",
            "#f032e6",
            "#bfef45",
            "#fabed4",
            "#469990",
            "#dcbeff",
            "#9A6324",
            "#fffac8",
            "#800000",
            "#aaffc3",
            "#808000",
            "#ffd8b1",
            "#000075",
            "#a9a9a9",
        ],
        alpha: float = 0.0,
        alpha_boundary: float = 1.0,
        mode: str = "inner",
    ) -> xr.Dataset:
        """
        Renders the segmentation mask with optional alpha blending and boundary rendering.

        Parameters:
            layer_key (str, optional): The key of the layer containing the segmentation mask. Default is Layers.SEGMENTATION.
            colors (List[str], optional): A list of colors to be used for rendering the segmentation mask. Default is ['white'].
            alpha (float, optional): The alpha value for blending the segmentation mask with the plot. Default is 0.0.
            alpha_boundary (float, optional): The alpha value for rendering the boundary of the segmentation mask. Default is 1.0.
            mode (str, optional): The mode for rendering the segmentation mask. Possible values are "inner" and "outer". Default is "inner".

        Returns:
            xr.Dataset: The modified xarray Dataset.

        Raises:
            AssertionError: If no segmentation layer is found in the object.

        Note:
            - The segmentation mask must be added to the object before calling this method.
            - The segmentation mask is expected to have a single channel with integer labels.
            - The rendered segmentation mask will be added as a new layer to the object.
        """
        assert (
            layer_key in self._obj
        ), f"Could not find segmentation layer with key {layer_key}. Please add a segmentation mask before calling this method."

        segmentation = self._obj[layer_key].values

        # the segmentation mask can either be 2D or 3D
        # if it is 2D, we transform it into 3D for compatibility with 3D segmentation masks (where multiple channels are present)
        if len(segmentation.shape) == 2:
            segmentation = np.expand_dims(segmentation, axis=0)
            channels = [1]
        else:
            channels = list(range(1, len(self._obj[layer_key].coords[Dims.CHANNELS]) + 1))

        # checking that there are as many colors as there are channels in the segmentation mask which is rendered
        assert (
            len(colors) >= segmentation.shape[0]
        ), f"Trying to render {segmentation.shape[0]} segmentation layers. Please provide custom colors using the colors argument."

        colors = colors[: len(channels)]

        if Layers.PLOT in self._obj:
            attrs = self._obj[Layers.PLOT].attrs
            rendered = _render_segmentation(
                segmentation,
                colors=colors,
                background="black",
                img=self._obj[Layers.PLOT].values,
                alpha=alpha,
                alpha_boundary=alpha_boundary,
                mode=mode,
            )
            self._obj = self._obj.drop_vars(Layers.PLOT)
        else:
            attrs = {}
            rendered = _render_segmentation(
                segmentation,
                colors=colors,
                background="black",
                alpha=alpha,
                alpha_boundary=alpha_boundary,
                mode=mode,
            )

        # adding segmentation colors to the attributes
        if Dims.CHANNELS in self._obj[layer_key].coords:
            attrs[Attrs.SEGMENTATION_COLORS] = {
                k.item(): v for k, v in zip(self._obj[layer_key].coords[Dims.CHANNELS], colors)
            }

        da = xr.DataArray(
            rendered,
            coords=[
                channels,
                self._obj.coords[Dims.Y],
                self._obj.coords[Dims.X],
                ["r", "g", "b", "a"],
            ],
            dims=[Dims.CHANNELS, Dims.Y, Dims.X, Dims.RGBA],
            name=Layers.PLOT,
            attrs=attrs,
        )

        # merging the masks together into a 2D array
        da = da.sum(Dims.CHANNELS, keep_attrs=True)
        da.values[da.values > 1] = 1.0

        return xr.merge([self._obj, da])

    def render_labels(
        self,
        alpha: float = 1.0,
        alpha_boundary: float = 1.0,
        mode: str = "inner",
        override_color: Optional[str] = None,
    ) -> xr.Dataset:
        """
        Renders cell type labels on the plot.

        Parameters:
            alpha (float, optional): The transparency of the labels. Defaults to 1.0.
            alpha_boundary (float, optional): The transparency of the label boundaries. Defaults to 1.0.
            mode (str, optional): The mode of rendering. Can be "inner" or "outer". Defaults to "inner".
            override_color (str, optional): The color to override the label colors. Defaults to None.

        Returns:
            xr.Dataset: The modified dataset with rendered labels.

        Raises:
            AssertionError: If no labels are found in the object.

        Notes:
            - This method requires labels to be present in the object. Add labels first using `la.predict_cell_types_argmax()` or `tl.astir()`.
            - The `mode` parameter determines whether the labels are rendered inside or outside the label boundaries.
            - The `override_color` parameter can be used to override the label colors with a single color.
        """
        assert (
            Layers.PROPERTIES in self._obj
        ), "No labels found in the object. Add labels first, for example by using la.predict_cell_types_argmax() or tl.astir()."

        color_dict = self._obj.la._label_to_dict(Props.COLOR, relabel=True)

        if override_color is not None:
            color_dict = {k: override_color for k in color_dict.keys()}

        cmap = _get_listed_colormap(color_dict)

        cells_dict = self._obj.la._cells_to_label(relabel=True)
        segmentation = self._obj[Layers.SEGMENTATION].values
        mask = _label_segmentation_mask(segmentation, cells_dict)

        if Layers.PLOT in self._obj:
            attrs = self._obj[Layers.PLOT].attrs
            rendered = _render_labels(
                mask,
                cmap,
                self._obj[Layers.PLOT].values,
                alpha=alpha,
                alpha_boundary=alpha_boundary,
                mode=mode,
            )
            self._obj = self._obj.drop_vars(Layers.PLOT)
        else:
            attrs = {}
            rendered = _render_labels(mask, cmap, alpha=alpha, alpha_boundary=alpha_boundary, mode=mode)

        da = xr.DataArray(
            rendered,
            coords=[
                self._obj.coords[Dims.Y],
                self._obj.coords[Dims.X],
                ["r", "g", "b", "a"],
            ],
            dims=[Dims.Y, Dims.X, Dims.RGBA],
            name=Layers.PLOT,
            attrs=attrs,
        )

        return xr.merge([self._obj, da])

    def imshow(
        self,
        legend_image: bool = False,
        legend_segmentation: bool = False,
        legend_label: bool = False,
        downsample: int = 1,
        legend_kwargs: dict = {"framealpha": 1},
        segmentation_kwargs: dict = {},
        ax=None,
    ):
        """
        Plots the image after rendering certain layers.
        Meant to be used in conjunction with pl.colorize(), pl.render_segmentation and pl.render_label().
        For a more high level wrapper, please refer to pl.show() instead.

        Parameters
        ----------
        legend_image : bool, optional
            Show the legendf for the channels. Default is False.
        legend_segmentation : bool, optional
            Show the legend for the segmentation. Default is False.
        legend_label : bool, optional
            Show the labels. Default is False.
        downsample : int, optional
            Downsample factor for the image. Default is 1.
        legend_kwargs : dict, optional
            Additional keyword arguments for configuring the legend. Default is {"framealpha": 1}.
        segmentation_kwargs : dict, optional
            Additional keyword arguments for rendering the segmentation, e. g. colors when rendering multiple segmentation channels. Default is {}.
        ax : matplotlib.axes, optional
            The matplotlib axis to plot on. If not provided, the current axis will be used.

        Returns
        -------
        xr.Dataset
            The updated image container.

        Notes
        -----
        - The function is used to plot images in conjunction with 'im.colorize' and 'la.render_label'.
        - The appearance of the plot and the inclusion of legends can be controlled using the respective parameters.
        """
        if Layers.PLOT not in self._obj:
            logger.warning("No plot defined yet. Plotting the first channel only. Please call pl.colorize() first.")
            channel = str(self._obj.coords[Dims.CHANNELS].values[0])
            self._obj = self._obj.pp[channel].pp.colorize(colors=["white"])

        if ax is None:
            ax = plt.gca()

        bounds = self._obj.pl._get_bounds()

        ax.imshow(
            self._obj[Layers.PLOT].values[::downsample, ::downsample],
            origin="lower",
            interpolation="none",
            extent=bounds,
        )

        legend = []

        if legend_image:
            legend += self._obj.pl._create_channel_legend()

        if legend_segmentation:
            legend += self._obj.pl._create_segmentation_legend()

        if legend_label:
            legend += self._obj.pl._create_label_legend()

        if legend_image or legend_segmentation or legend_label:
            ax.legend(handles=legend, **legend_kwargs)

        return self._obj

    def scatter_labels(
        self,
        legend: bool = True,
        size: float = 1.0,
        alpha: float = 0.9,
        zorder: int = 10,
        ax=None,
        legend_kwargs: dict = {"framealpha": 1},
        scatter_kwargs: dict = {},
    ) -> xr.Dataset:
        """
        Scatter plot of labeled cells.

        Parameters:
        -----------
        legend : bool, optional
            Whether to show the legend. Default is True.
        size : float, optional
            Size of the scatter markers. Default is 1.0.
        alpha : float, optional
            Transparency of the scatter markers. Default is 0.9.
        zorder : int, optional
            The z-order of the scatter markers. Default is 10.
        ax : matplotlib.axes.Axes, optional
            The axes on which to plot the scatter. If not provided, the current axes will be used.
        legend_kwargs : dict, optional
            Additional keyword arguments for configuring the legend. Default is {"framealpha": 1}.
        scatter_kwargs : dict, optional
            Additional keyword arguments for configuring the scatter plot.

        Returns:
        --------
        xr.Dataset
            The modified spatialproteomics object.
        """
        if ax is None:
            ax = plt.gca()

        color_dict = self._obj.la._label_to_dict(Props.COLOR)
        label_dict = self._obj.la._cells_to_label()

        for celltype in label_dict.keys():
            label_subset = self._obj.la[celltype]
            obs_layer = label_subset[Layers.OBS]
            x = obs_layer.loc[:, Features.X]
            y = obs_layer.loc[:, Features.Y]
            ax.scatter(x.values, y.values, s=size, c=color_dict[celltype], alpha=alpha, zorder=zorder, **scatter_kwargs)

        xmin, xmax, ymin, ymax = self._obj.pl._get_bounds()
        ax.set_ylim([ymin, ymax])
        ax.set_xlim([xmin, xmax])

        if legend:
            legend = self._obj.pl._create_label_legend()
            ax.legend(handles=legend, **legend_kwargs).set_zorder(102)

        return self._obj

    def scatter(
        self,
        feature: str,
        palette: dict = None,
        legend: bool = True,
        layer_key: str = Layers.OBS,
        size: float = 1.0,
        alpha: float = 0.9,
        zorder: int = 10,
        ax=None,
        legend_kwargs: dict = {"framealpha": 1},
        scatter_kws: dict = {},
    ) -> xr.Dataset:
        """
        Create a scatter plot of some feature. At the moment, only categorical features are supported.

        Parameters:
        - feature (str): The feature to be plotted.
        - palette (dict, optional): A dictionary mapping feature values to colors. If not provided, a default palette will be used.
        - legend (bool, optional): Whether to show the legend. Default is True.
        - layer_key (str, optional): The key of the layer to be plotted. Default is Layers.OBS.
        - size (float, optional): The size of the scatter points. Default is 1.0.
        - alpha (float, optional): The transparency of the scatter points. Default is 0.9.
        - zorder (int, optional): The z-order of the scatter points. Default is 10.
        - ax (object, optional): The matplotlib axes object to plot on. If not provided, the current axes will be used.
        - legend_kwargs (dict, optional): Additional keyword arguments for configuring the legend. Default is {"framealpha": 1}.
        - scatter_kws (dict, optional): Additional keyword arguments for configuring the scatter plot. Default is {}.

        Returns:
        - xr.Dataset: The original data object.

        Raises:
        - AssertionError: If the layer_key is not found in the data object.
        - AssertionError: If the feature is not found in the specified layer.
        - AssertionError: If the X or Y coordinates are not found in the specified layer.
        - AssertionError: If the number of unique feature values is greater than 10 and no color_scheme is provided.
        - AssertionError: If not all unique feature values are present in the provided palette.

        """
        if ax is None:
            ax = plt.gca()

        # check if the layer exists
        assert layer_key in self._obj, f"Layer {layer_key} not found in the data object."

        layer = self._obj[layer_key]

        # check that the feature exists
        assert feature in layer.coords[Dims.FEATURES], f"Feature {feature} not found in the layer {layer_key}."

        # check if the layer contains X and Y coordinates
        assert Features.X in layer.coords[Dims.FEATURES], f"Feature {Features.X} not found in the layer {layer_key}."
        assert Features.Y in layer.coords[Dims.FEATURES], f"Feature {Features.Y} not found in the layer {layer_key}."

        x = layer.loc[:, Features.X]
        y = layer.loc[:, Features.Y]

        if palette is None:
            # Default palette
            unique_values = np.unique(layer.sel(features=feature))
            assert (
                len(unique_values) <= 10
            ), "Scatter currently only supports categorical features with 10 or fewer unique values. If you want more than 10 features, please provide a color_scheme."
            colors = plt.cm.tab10(np.linspace(0, 1, len(unique_values)))  # Using tab10 colormap for 10 unique colors
            color_dict = {val: color for val, color in zip(unique_values, colors)}
        else:
            color_dict = palette
            # check if all unique values are present in the palette
            assert set(np.unique(layer.sel(features=feature))) <= set(
                color_dict.keys()
            ), f"Not all values are present in the palette. Make sure the following keys are in your palette: {np.unique(layer.sel(features=feature))}."

        # Assigning colors based on feature values
        colors = [color_dict.get(val, "gray") for val in layer.sel(features=feature).values]

        ax.scatter(x.values, y.values, color=colors, s=size, alpha=alpha, zorder=zorder, **scatter_kws)

        xmin, xmax, ymin, ymax = self._obj.pl._get_bounds()
        ax.set_ylim([ymin, ymax])
        ax.set_xlim([xmin, xmax])

        ax.set_aspect("equal")  # Set equal aspect ratio for x and y axes

        if legend:
            # Creating legend labels based on unique feature values
            legend_handles = [
                plt.Line2D([0], [0], marker="o", color="w", markersize=5, markerfacecolor=color, label=val)
                for val, color in color_dict.items()
            ]
            ax.legend(handles=legend_handles, **legend_kwargs).set_zorder(102)

        return self._obj

    def add_box(
        self,
        xlim: List[int],
        ylim: List[int],
        color: str = "w",
        linewidth: float = 2,
        ax=None,
    ):
        """
        Adds a box to the current plot.

        Parameters
        ----------
        xlim : List[int]
            The x-bounds of the box [xstart, xstop].
        ylim : List[int]
            The y-bounds of the box [ymin, ymax].
        color : str, optional
            The color of the box. Default is "w" (white).
        linewidth : float, optional
            The linewidth of the box. Default is 2.
        ax : matplotlib.axes, optional
            The matplotlib axis to plot on. If not provided, the current axis will be used.

        Returns
        -------
        xr.Dataset
            The updated spatialproteomics object.

        Notes
        -----
        - The function adds a rectangular box to the current plot with specified x and y bounds.
        - The box can be customized using the 'color' and 'linewidth' parameters.
        """

        if ax is None:
            ax = plt.gca()

        # unpack data
        xmin, xmax = xlim
        ymin, ymax = ylim

        ax.hlines(xmin=xmin, xmax=xmax, y=ymin, color=color, linewidth=linewidth)
        ax.hlines(xmin=xmin, xmax=xmax, y=ymax, color=color, linewidth=linewidth)
        ax.vlines(ymin=ymin, ymax=ymax, x=xmin, color=color, linewidth=linewidth)
        ax.vlines(ymin=ymin, ymax=ymax, x=xmax, color=color, linewidth=linewidth)

        return self._obj

    def autocrop(
        self, padding: int = 50, downsample: int = 10, key: str = Layers.IMAGE, channel: Optional[str] = None
    ) -> xr.Dataset:

        """
        Crop the image so that the background surrounding the tissue/TMA gets cropped away.

        Parameters:
        - padding (int): The padding to be added around the cropped image in pixels. Default is 50.
        - downsample (int): The downsampling factor for the image. Default is 10.
        - key (str): The key of the image to be cropped. Default is Layers.IMAGE.
        - channel (str, optional): The channel used for cropping. Default is None, which defaults to using the first available channel.

        Returns:
        - obj.pp (object): The cropped image.
        """
        if channel is None:
            channel = self._obj.coords[Dims.CHANNELS].values.tolist()[0]
        img = self._obj.pp[channel].pp.downsample(downsample)[key].values.squeeze()
        slices = _autocrop(img, downsample=downsample, padding=padding)
        return self._obj.pp[slices[0], slices[1]]
