from typing import List, Optional, Union

import numpy as np
import pandas as pd
import xarray as xr

from ..constants import Dims, Layers
from ..pp.utils import handle_disconnected_cells


@xr.register_dataset_accessor("ext")
class ExternalAccessor:
    """The external accessor enables the application of external tools such as StarDist or Astir"""

    def __init__(self, xarray_obj):
        self._obj = xarray_obj

    def cellpose(
        self,
        channels: Optional[Union[List[str], str]] = None,
        key_added: Optional[str] = Layers.SEGMENTATION,
        diameter: int = 0,
        channel_settings: list = [0, 0],
        num_iterations: int = 2000,
        cellprob_threshold: float = 0.0,
        flow_threshold: float = 0.4,
        gpu: bool = True,
        model_type: str = "cyto3",
        return_xarray: bool = True,
        handle_disconnected: str = "keep_largest",
    ):
        """
        Segment cells using Cellpose.

        Parameters
        ----------
        channels: List[str], optional
            List of channels to use for segmentation. If None, all channels are used.
        key_added : str, optional
            Key to assign to the segmentation results.
        diameter : int, optional
            Expected cell diameter in pixels.
        channel_settings : List[int], optional
            Channels for Cellpose to use for segmentation.
        num_iterations : int, optional
            Maximum number of iterations for segmentation.
        gpu : bool, optional
            Whether to use GPU for segmentation.
        model_type : str, optional
            Type of Cellpose model to use.
        return_xarray: bool, optional
            Whether to return the segmentation as an xarray DataArray or as a numpy array.

        Returns
        -------
        xr.Dataset
            Dataset containing original data and segmentation mask.

        Notes
        -----
        This method requires the 'cellpose' package to be installed.
        """

        if return_xarray:
            # if return_xarray is true, check if a segmentation mask with the key already exists
            assert (
                key_added not in self._obj
            ), f"A segmentation mask with the key {key_added} already exists. You can either change the key with the key_added parameter, or return the predictions as a numpy array. To do this, set return_xarray to False. Alternatively, you can drop the existing segmentation mask from the object by using pp.drop_layers('{key_added}')."

            # if the number of channels is 1, we can add the segmentation to the original object
            # if it is equal to the number of channels, we can also add it to the object
            # if it is anything else, we force the user to return the predictions in the form of a numpy array
            assert len(channels) == 1 or len(channels) == len(
                self._obj.coords[Dims.CHANNELS].values
            ), "You are trying to segment only a subset of the available channels. If you want to add the segmentation mask to the xarray object directly, you need to segment either all channels or only one channel. If you want to segment a subset of the channels, you need to return the predictions as a numpy array."

        from cellpose import models

        model = models.Cellpose(gpu=gpu, model_type=model_type)

        if isinstance(channels, str):
            channels = [channels]
        elif channels is None:
            channels = self._obj.coords[Dims.CHANNELS].values

        all_masks = []
        for channel in channels:
            masks_pred, _, _, _ = model.eval(
                self._obj.pp[channel]._image.values.squeeze(),
                diameter=diameter,
                channels=channel_settings,
                niter=num_iterations,
                cellprob_threshold=cellprob_threshold,
                flow_threshold=flow_threshold,
            )

            # checking if there are any disconnected cells in the input
            handle_disconnected_cells(masks_pred, handle_disconnected)

            all_masks.append(masks_pred)

        if len(all_masks) == 1:
            mask_tensor = np.expand_dims(all_masks[0], 0)
        else:
            mask_tensor = np.stack(all_masks, 0)

        if not return_xarray:
            return mask_tensor

        # if there is one channel, we can squeeze the mask tensor
        if len(channels) == 1:
            da = xr.DataArray(
                mask_tensor.squeeze(),
                coords=[self._obj.coords[Dims.Y], self._obj.coords[Dims.X]],
                dims=[Dims.Y, Dims.X],
                name=key_added,
            )
        # if we segment on all of the channels, we need to add the channel dimension
        else:
            da = xr.DataArray(
                mask_tensor,
                coords=[
                    self._obj.coords[Dims.CHANNELS],
                    self._obj.coords[Dims.Y],
                    self._obj.coords[Dims.X],
                ],
                dims=[Dims.CHANNELS, Dims.Y, Dims.X],
                name=key_added,
            )

        return xr.merge([self._obj, da])

    def cellpose_denoise(
        self,
        key_added: List[str] = ["_cellpose_denoise", "_cellpose_denoise_segmentation"],
        diameter: int = 0,
        channel_settings: list = [0, 0],
        gpu: bool = True,
        model_type: str = "cyto3",
        restore_type: str = "denoise_cyto3",
        **kwargs,
    ):
        """
        Segment cells using Cellpose.

        Parameters
        ----------
        key_added : str, optional
            Key to assign to the segmentation results.
        diameter : int, optional
            Expected cell diameter in pixels.
        channel_settings : List[int], optional
            Channels for Cellpose to use for segmentation.
        num_iterations : int, optional
            Maximum number of iterations for segmentation.
        gpu : bool, optional
            Whether to use GPU for segmentation.
        model_type : str, optional
            Type of Cellpose model to use.

        Returns
        -------
        xr.Dataset
            Dataset containing original data and segmentation mask.

        Notes
        -----
        This method requires the 'cellpose' package to be installed.
        """

        from cellpose import denoise

        model = denoise.CellposeDenoiseModel(gpu=gpu, model_type=model_type, restore_type=restore_type)

        all_masks = []
        all_imags = []
        for channel in self._obj.coords[Dims.CHANNELS]:
            masks, flows, styles, imgs_dn = model.eval(
                self._obj.pp[channel.item()]._image.values.squeeze(),
                diameter=diameter,
                channels=channel_settings,
                **kwargs,
            )
            all_masks.append(masks)
            all_imags.append(imgs_dn)

        if len(all_masks) == 1:
            mask_tensor = np.expand_dims(all_masks[0], 0)
            img_tensor = np.expand_dims(all_imags[0], 0)
        else:
            mask_tensor = np.stack(all_masks, 0)
            img_tensor = np.stack(all_imags, 0)

        da = xr.DataArray(
            mask_tensor,
            coords=[
                self._obj.coords[Dims.CHANNELS],
                self._obj.coords[Dims.Y],
                self._obj.coords[Dims.X],
            ],
            dims=[Dims.CHANNELS, Dims.Y, Dims.X],
            name=key_added[1],
        )
        db = xr.DataArray(
            img_tensor,
            coords=[
                self._obj.coords[Dims.CHANNELS],
                self._obj.coords[Dims.Y],
                self._obj.coords[Dims.X],
            ],
            dims=[Dims.CHANNELS, Dims.Y, Dims.X],
            name=key_added[0],
        )
        return xr.merge([self._obj, da, db])

    def stardist(
        self,
        scale: float = 3,
        n_tiles: int = 12,
        normalize: bool = True,
        nuclear_channel: str = "DAPI",
        predict_big: bool = False,
        handle_disconnected: str = "keep_largest",
        **kwargs,
    ) -> xr.Dataset:
        """
        Apply StarDist algorithm to perform instance segmentation on the nuclear image.

        Parameters:
        ----------
        scale : float, optional
            Scaling factor for the StarDist model (default is 3).
        n_tiles : int, optional
            Number of tiles to split the image into for prediction (default is 12).
        normalize : bool, optional
            Flag indicating whether to normalize the nuclear image (default is True).
        nuclear_channel : str, optional
            Name of the nuclear channel in the image (default is "DAPI").
        predict_big : bool, optional
            Flag indicating whether to use the 'predict_instances_big' method for large images (default is False).
        **kwargs : dict, optional
            Additional keyword arguments to be passed to the StarDist prediction method.

        Returns:
        -------
        obj : xr.Dataset
            Xarray dataset containing the segmentation mask and centroids.

        Raises:
        ------
        ValueError
            If the object already contains a segmentation mask.

        """
        import csbdeep.utils
        from stardist.models import StarDist2D

        if Layers.SEGMENTATION in self._obj:
            raise ValueError("The object already contains a segmentation mask. StarDist will not be executed.")

        # getting the nuclear image
        nuclear_img = self._obj.pp[nuclear_channel].to_array().values.squeeze()

        # normalizing the image
        if normalize:
            nuclear_img = csbdeep.utils.normalize(nuclear_img)

        # Load the StarDist model
        model = StarDist2D.from_pretrained("2D_versatile_fluo")

        # Predict the label image (different methods for large or small images, see the StarDist documentation for more details)
        if predict_big:
            labels, _ = model.predict_instances_big(nuclear_img, scale=scale, **kwargs)
        else:
            labels, _ = model.predict_instances(nuclear_img, scale=scale, n_tiles=(n_tiles, n_tiles), **kwargs)

        # checking if there are any disconnected cells in the input
        handle_disconnected_cells(labels, handle_disconnected)

        # Adding the segmentation mask  and centroids to the xarray dataset
        return self._obj.pp.add_segmentation(labels).pp.add_observations()

    def astir(
        self,
        marker_dict: dict,
        key: str = Layers.INTENSITY,
        threshold: float = 0,
        seed: int = 42,
        learning_rate: float = 0.001,
        batch_size: float = 64,
        n_init: int = 5,
        n_init_epochs: int = 5,
        max_epochs: int = 500,
        cell_id_col: str = "cell_id",
        cell_type_col: str = "cell_type",
        **kwargs,
    ):
        """
        This method predicts cell types from an expression matrix using the Astir algorithm.

        Parameters
        ----------
        marker_dict : dict
            Dictionary mapping markers to cell types. Can also include cell states. Example: {"cell_type": {'B': ['PAX5'], 'T': ['CD3'], 'Myeloid': ['CD11b']}}
        key : str, optional
            Layer to use as expression matrix.
        threshold : float, optional
            Certainty threshold for astir to assign a cell type. Defaults to 0.
        seed : int, optional
            Random seed. Defaults to 42.
        learning_rate : float, optional
            Learning rate. Defaults to 0.001.
        batch_size : float, optional
            Batch size. Defaults to 64.
        n_init : int, optional
            Number of initializations. Defaults to 5.
        n_init_epochs : int, optional
            Number of epochs for each initialization. Defaults to 5.
        max_epochs : int, optional
            Maximum number of epochs. Defaults to 500.
        cell_id_col : str, optional
            Column name for cell IDs. Defaults to "cell_id".
        cell_type_col : str, optional
            Column name for cell types. Defaults to "cell_type".

        Raises
        ------
        ValueError
            If no expression matrix was present or the image is not of type uint8.

        Returns
        -------
        DataArray
            A DataArray with the assigned cell types.
        """
        import astir
        import torch

        # check if there is an expression matrix
        if key not in self._obj:
            raise ValueError(
                f"No expression matrix with key {key} found in the object. Make sure to call pp.quantify first."
            )

        # raise an error if the image is of anything other than uint8
        if self._obj[Layers.IMAGE].dtype != "uint8":
            raise ValueError(
                "The image is not of type uint8, which is required for astir to work properly. Use the dtype argument in add_quantification() to convert the image to uint8."
            )

        # converting the xarray to a pandas dataframe to keep track of channel names and indices after running astir
        expression_df = pd.DataFrame(self._obj[key].values, columns=self._obj.coords[Dims.CHANNELS].values)
        expression_df.index = self._obj.coords[Dims.CELLS].values

        # running astir
        model = astir.Astir(expression_df, marker_dict, dtype=torch.float64, random_seed=seed)
        model.fit_type(
            learning_rate=learning_rate,
            batch_size=batch_size,
            n_init=n_init,
            n_init_epochs=n_init_epochs,
            max_epochs=max_epochs,
            **kwargs,
        )

        # getting the predictions
        assigned_cell_types = model.get_celltypes(threshold=threshold)
        # assign the index to its own column
        assigned_cell_types = assigned_cell_types.reset_index()
        # renaming the columns
        assigned_cell_types.columns = [cell_id_col, cell_type_col]
        # setting the cell dtype to int
        assigned_cell_types[cell_id_col] = assigned_cell_types[cell_id_col].astype(int)

        # adding the labels to the xarray object
        return self._obj.pp.add_labels(assigned_cell_types, cell_col=cell_id_col, label_col=cell_type_col)

    def convert_to_anndata(
        self,
        expression_matrix_key: str = Layers.INTENSITY,
        obs_key: str = Layers.OBS,
        additional_layers: Optional[dict] = None,
        additional_uns: Optional[dict] = None,
    ):
        import anndata

        # checking that the expression matrix key is present in the object
        assert (
            expression_matrix_key in self._obj
        ), f"Expression matrix key {expression_matrix_key} not found in the object. Set the expression matrix key with the expression_matrix_key argument."

        expression_matrix = self._obj[expression_matrix_key].values
        adata = anndata.AnnData(expression_matrix)
        if additional_layers:
            for key, layer in additional_layers.items():
                # checking that the additional layer is present in the object
                assert layer in self._obj, f"Layer {layer} not found in the object."
                adata.layers[key] = self._obj[layer].values
        adata.var_names = self._obj.coords[Dims.CHANNELS].values

        if obs_key in self._obj:
            adata.obs = pd.DataFrame(self._obj[obs_key], columns=self._obj.coords[Dims.FEATURES])

        if additional_uns:
            for key, layer in additional_uns.items():
                # checking that the additional layer is present in the object
                assert layer in self._obj, f"Layer {layer} not found in the object."
                adata.uns[key] = self._obj.pp.get_layer_as_df(layer)

        return adata

    def convert_to_spatialdata(
        self, image_key: str = Layers.IMAGE, segmentation_key: str = Layers.SEGMENTATION, **kwargs
    ):
        import spatialdata

        markers = self._obj.coords[Dims.CHANNELS].values
        cells = self._obj.coords[Dims.CELLS].values
        image = spatialdata.models.Image2DModel.parse(
            self._obj[image_key].values, transformations=None, dims=("c", "x", "y"), c_coords=markers
        )
        segmentation = spatialdata.models.Labels2DModel.parse(
            self._obj[segmentation_key].values, transformations=None, dims=("x", "y")
        )

        adata = self._obj.ext.convert_to_anndata(**kwargs)

        # the anndata object within the spatialdata object requires some additional slots, which are created here
        adata.uns["spatialdata_attrs"] = {"region": "segmentation", "region_key": "region", "instance_key": "id"}

        obs_df = pd.DataFrame(
            {
                "id": cells,
                "region": pd.Series(["segmentation"] * len(cells)).astype(
                    pd.api.types.CategoricalDtype(categories=["segmentation"])
                ),
            }
        )
        adata.obs = obs_df

        spatial_data_object = spatialdata.SpatialData(
            images={"image": image}, labels={"segmentation": segmentation}, table=adata
        )

        return spatial_data_object
