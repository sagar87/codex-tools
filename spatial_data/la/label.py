from typing import Callable, List, Union

import networkx as nx
import numpy as np
import pandas as pd
import xarray as xr
from skimage.segmentation import find_boundaries, relabel_sequential
from sklearn.neighbors import NearestNeighbors

from ..base_logger import logger
from ..constants import COLORS, Dims, Features, Layers, Props
from ..pl import _get_listed_colormap
from ..se.segmentation import _remove_unlabeled_cells

# from tqdm import tqdm


def _format_labels(labels):
    """Formats a label list."""
    formatted_labels = labels.copy()
    unique_labels = np.unique(labels)

    if 0 in unique_labels:
        logger.warning("Found 0 in labels. Reindexing ...")
        formatted_labels += 1

    if ~np.all(np.diff(unique_labels) == 1):
        logger.warning("Labels are non-consecutive. Relabeling ...")
        formatted_labels, _, _ = relabel_sequential(formatted_labels)

    return formatted_labels


def _label_segmentation_mask(segmentation: np.ndarray, annotations: dict) -> np.ndarray:
    """
    Relabels a segmentation according to the annotations df (contains the columns type, cell).
    """
    labeled_segmentation = segmentation.copy()
    all_cells = []

    for k, v in annotations.items():
        mask = np.isin(segmentation, v)
        labeled_segmentation[mask] = k
        all_cells.extend(v)

    # remove cells that are not indexed
    neg_mask = ~np.isin(segmentation, all_cells)
    labeled_segmentation[neg_mask] = 0

    return labeled_segmentation


def _remove_segmentation_mask_labels(segmentation: np.ndarray, labels: Union[list, np.ndarray]) -> np.ndarray:
    """
    Relabels a segmentation according to the labels df (contains the columns type, cell).
    """
    labeled_segmentation = segmentation.copy()
    mask = ~np.isin(segmentation, labels)
    labeled_segmentation[mask] = 0

    return labeled_segmentation


def _render_label(mask, cmap_mask, img=None, alpha=0.2, alpha_boundary=1.0, mode="inner"):
    colored_mask = cmap_mask(mask)

    mask_bool = mask > 0
    mask_bound = np.bitwise_and(mask_bool, find_boundaries(mask, mode=mode))

    # blend
    if img is None:
        img = np.zeros(mask.shape + (4,), np.float32)
        img[..., -1] = 1

    im = img.copy()

    im[mask_bool] = alpha * colored_mask[mask_bool] + (1 - alpha) * img[mask_bool]
    im[mask_bound] = alpha_boundary * colored_mask[mask_bound] + (1 - alpha_boundary) * img[mask_bound]

    return im


@xr.register_dataset_accessor("la")
class LabelAccessor:
    def __init__(self, xarray_obj):
        self._obj = xarray_obj

    def _relabel_dict(self, dictionary: dict):
        _, fw, _ = relabel_sequential(self._obj.coords[Dims.LABELS].values)
        return {fw[k]: v for k, v in dictionary.items()}

    def _label_to_dict(self, prop: str, reverse: bool = False, relabel: bool = False):
        """Returns a dictionary that maps each label to a list to their property.

        Parameters:
        -----------
        prop: str
            The property to map to the labels.
        reverse: bool
            If True, the dictionary will be reversed.
        relabel: bool
            Deprecated.

        Returns:
        --------
        label_dict: dict
            A dictionary that maps each label to a list to their property.
        """
        labels_layer = self._obj[Layers.LABELS]
        label_dict = {label.item(): labels_layer.loc[label, prop].item() for label in self._obj.coords[Dims.LABELS]}

        if relabel:
            return self._obj.la._relabel_dict(label_dict)

        if reverse:
            label_dict = {v: k for k, v in label_dict.items()}

        return label_dict

    def _cells_to_label(self, relabel: bool = False, include_unlabeled: bool = False):
        """Returns a dictionary that maps each label to a list of cells."""

        label_dict = {
            label.item(): self._obj.la._filter_cells_by_label(label.item()) for label in self._obj.coords[Dims.LABELS]
        }

        if include_unlabeled:
            label_dict[0] = self._obj.la._filter_cells_by_label(0)

        if relabel:
            return self._obj.la._relabel_dict(label_dict)

        return label_dict

    def _filter_cells_by_label(self, items: Union[int, List[int]]):
        """Returns the list of cells with the labels from items."""
        if type(items) is int:
            items = [items]

        cells = self._obj[Layers.OBS].loc[:, Features.LABELS].values.copy()
        cells_bool = np.isin(cells, items)
        cells_sel = self._obj.coords[Dims.CELLS][cells_bool].values

        return cells_sel

    def filter_by_obs(self, col: str, func: Callable):
        """Returns the list of cells with the labels from items."""
        cells = self._obj[Layers.OBS].sel({Dims.FEATURES: col}).values.copy()
        cells_bool = func(cells)
        cells_sel = self._obj.coords[Dims.CELLS][cells_bool].values
        # print(cells_sel, len(cells_sel))
        return self._obj.sel({Dims.CELLS: cells_sel})

    def filter_by_intensity(self, col: str, func: Callable):
        """Returns the list of cells with the labels from items."""
        cells = self._obj[Layers.INTENSITY].sel({Dims.CHANNELS: col}).values.copy()
        cells_bool = func(cells)
        cells_sel = self._obj.coords[Dims.CELLS][cells_bool].values

        return self._obj.sel({Dims.CELLS: cells_sel})

    def __getitem__(self, indices):
        """
        Sub selects labels.
        """
        # type checking
        # TODO: Write more tests!
        if isinstance(indices, float):
            raise TypeError("Label indices must be valid integers, str, slices, List[int] or List[str].")

        if isinstance(indices, int):
            if indices not in self._obj.coords[Dims.LABELS].values:
                raise ValueError(f"Label type {indices} not found.")

            sel = [indices]

        if isinstance(indices, str):
            label_dict = self._obj.la._label_to_dict(Props.NAME, reverse=True)

            if indices not in label_dict:
                raise ValueError(f"Label type {indices} not found.")

            sel = [label_dict[indices]]

        if isinstance(indices, slice):
            l_start = indices.start if indices.start is not None else 1
            l_stop = indices.stop if indices.stop is not None else self._obj.dims[Dims.LABELS]
            sel = [i for i in range(l_start, l_stop)]

        if isinstance(indices, (list, tuple)):
            if not all([isinstance(i, (str, int)) for i in indices]):
                raise TypeError("Label indices must be valid integers, str, slices, List[int] or List[str].")

            sel = []
            for i in indices:
                if isinstance(i, str):
                    label_dict = self._obj.la._label_to_dict(Props.NAME, reverse=True)

                    if i not in label_dict:
                        raise ValueError(f"Label type {i} not found.")

                    sel.append(label_dict[i])

                if isinstance(i, int):
                    if i not in self._obj.coords[Dims.LABELS].values:
                        raise ValueError(f"Label type {i} not found.")

                    sel.append(i)

        cells = self._obj.la._filter_cells_by_label(sel)
        return self._obj.sel({Dims.LABELS: sel, Dims.CELLS: cells})

    def deselect(self, indices):
        # REFACTOR
        if type(indices) is slice:
            l_start = indices.start if indices.start is not None else 1
            l_stop = indices.stop if indices.stop is not None else self._obj.dims[Dims.LABELS]
            sel = [i for i in range(l_start, l_stop)]
        elif type(indices) is list:
            assert all([isinstance(i, (int, str)) for i in indices]), "All label indices must be integers."
            sel = indices

        elif type(indices) is tuple:
            indices = list(indices)
            all_int = all([type(i) is int for i in indices])
            assert all_int, "All label indices must be integers."
            sel = indices
        else:
            assert type(indices) is int, "Label must be provided as slices, lists, tuple or int."

            sel = [indices]

        total_labels = self._obj.dims[Dims.LABELS] + 1
        inv_sel = [i for i in range(1, total_labels) if i not in sel]
        cells = self._obj.la._filter_cells_by_label(inv_sel)
        return self._obj.sel({Dims.LABELS: inv_sel, Dims.CELLS: cells})

    def add_label_type(self, name: str, color: str = "w"):
        """Add a new label type to the image container."""

        if Layers.SEGMENTATION not in self._obj:
            raise ValueError("No segmentation mask found.")
        if Layers.OBS not in self._obj:
            raise ValueError("No observation table found.")

        array = np.array([name, color]).reshape(1, -1)

        # if label annotations (Layers.LABELS) are not present, create them
        if Layers.LABELS not in self._obj:
            da = xr.DataArray(
                array,
                coords=[np.array([1]), [Props.NAME, Props.COLOR]],
                dims=[Dims.LABELS, Dims.PROPS],
                name=Layers.LABELS,
            )

            db = xr.DataArray(
                np.zeros(self._obj.coords[Dims.CELLS].shape[0]).reshape(-1, 1),
                coords=[self._obj.coords[Dims.CELLS], [Features.LABELS]],
                dims=[Dims.CELLS, Dims.FEATURES],
                name=Layers.OBS,
            )

            obj = xr.merge([self._obj, da, db])
        else:
            new_coord = self._obj.coords[Dims.LABELS].values.max() + 1
            da = xr.DataArray(
                array,
                coords=[np.array([new_coord]), [Props.NAME, Props.COLOR]],
                dims=[Dims.LABELS, Dims.PROPS],
            )

            da = xr.concat(
                [self._obj[Layers.LABELS], da],
                dim=Dims.LABELS,
            )
            obj = xr.merge([self._obj, da])

        return obj

    def remove_label_type(self, cell_type: Union[int, List[int]]):

        if isinstance(cell_type, int):
            cell_type = [cell_type]

        if Layers.LABELS not in self._obj:
            raise ValueError("No cell type labels found.")

        for i in cell_type:
            if i not in self._obj.coords[Dims.LABELS].values:
                raise ValueError(f"Cell type {i} not found.")

        cells_bool = (self._obj[Layers.OBS].sel({Dims.FEATURES: Features.LABELS}) == cell_type).values
        cells = self._obj.coords[Dims.CELLS][cells_bool].values

        self._obj[Layers.OBS].loc[{Dims.FEATURES: Features.LABELS, Dims.CELLS: cells}] = 0

        return self._obj.sel({Dims.LABELS: [i for i in self._obj.coords[Dims.LABELS] if i not in cell_type]})

    def get_gate_graph(self, pop: bool = False):
        if "graph" not in self._obj.attrs:
            # initialize graph
            graph = nx.DiGraph()
            graph.add_node(
                0,
                label_name="Unlabeled",
                label_id=0,
                channel=None,
                threshold=None,
                intensity_key=None,
                override=None,
                step=0,
            )

            # graph.add_node(0)
            # self._obj.attrs["graph"] = nx.to_dict_of_dicts(graph)
            return graph

        # pop and initialise graph
        obj = self._obj
        if pop:
            graph_dict = obj.attrs.pop("graph")
        else:
            graph_dict = obj.attrs["graph"]

        graph = nx.from_dict_of_dicts(graph_dict, create_using=nx.DiGraph)

        attrs_keys = list(obj.attrs.keys())
        for key in attrs_keys:
            if pop:
                node_attributes = obj.attrs.pop(key)
            else:
                if key == "graph":
                    continue
                node_attributes = obj.attrs[key]

            nx.set_node_attributes(graph, node_attributes, name=key)

        return graph

    def gate_label_type(
        self,
        label_id: Union[int, str],
        channel: str,
        threshold: float,
        intensity_key: str,
        override: bool = False,
        parent: Union[int, str] = 0,
    ):
        """

        Parameters:
        -----------
        label_id: int
            The cell type id to assign to the gated cells.
        channel: str
            The channel to use for gating.
        threshold: float
            The threshold to use for gating.
        intensity_key: str
            The key to use for the intensity layer.
        override: bool
            Whether to override the existing descendant label types.
        """
        labels = self._obj.coords[Dims.LABELS]
        label_names_reverse = self._obj.la._label_to_dict(Props.NAME, reverse=True)

        if isinstance(label_id, str):
            if label_id not in label_names_reverse:
                raise ValueError(f"Cell type {label_id} not found.")

            # overwrite label_id with the corresponding id
            label_id = label_names_reverse[label_id]

        if isinstance(parent, str):
            if parent not in label_names_reverse:
                raise ValueError(f"Cell type {parent} not found.")

            parent = label_names_reverse[parent]

        if label_id not in labels:
            raise ValueError(f"Cell type id {label_id} not found.")

        label_names = self._obj.la._label_to_dict(Props.NAME)  # dict of label names per label id
        labeled_cells = self._obj.la._cells_to_label(include_unlabeled=True)  # dict of cell ids per label
        graph = self._obj.la.get_gate_graph(pop=False)  # gating graph
        step = max(list(nx.get_node_attributes(graph, "step").values())) + 1  # keeps track of the current gating step

        # print(graph.nodes)

        # should use filter
        cells_bool = (self._obj[intensity_key].sel({Dims.CHANNELS: channel}) > threshold).values
        cells = self._obj.coords[Dims.CELLS].values
        cells_gated = cells[cells_bool]

        if override:
            print("descendants", nx.descendants(graph, parent))
            descendants = [parent] + list(nx.descendants(graph, parent))
            cells_available = []
            for descendant in descendants:
                cells_available.append(labeled_cells[descendant])

            cells_available = np.concatenate(cells_available)
        else:
            cells_available = labeled_cells[parent]

        cells_selected = cells_gated[np.isin(cells_gated, cells_available)]
        # print(cells_selected)

        logger.info(
            f"Gating yields {len(cells_selected)} of positive {len(cells_gated)} labels (availale cells {len(cells_available)})."
        )

        # not_overriden = {}

        # for other_label, other_cells in labeled_cells.items():
        #     # if it is not a top level node
        #     if parent != 0:
        #         if other_label != parent:
        #             cells_gated = np.array([cell for cell in cells_gated if cell not in other_cells])
        #             not_overriden[other_label] = [cell for cell in cells_gated if cell not in other_cells]

        #             logger.info(
        #                 f"Removing {num_cells_overwritten} labels {label_names[label_id]} ({label_id}) to prevent overwriting cell type {label_names[other_label]} ({other_label}). New number of positive labels: {len(cells_gated)}."
        #             )

        #             continue

        #     overlap = np.isin(cells_gated, other_cells)
        #     num_cells_overwritten = np.sum(overlap)

        #     if np.any(overlap):
        #         if override:
        #             logger.info(
        #                 f"{num_cells_overwritten} cells of cell type {label_names[other_label]} ({other_label}) is being overwritten by cell type {label_names[label_id]} ({label_id})."
        #             )
        #         else:
        #             cells_gated = np.array([cell for cell in cells_gated if cell not in other_cells])

        #             logger.info(
        #                 f"Removing {num_cells_overwritten} labels {label_names[label_id]} ({label_id}) to prevent overwriting cell type {label_names[other_label]} ({other_label}). New number of positive labels: {len(cells_gated)}."
        #             )

        obs = self._obj[Layers.OBS]
        obj = self._obj.drop_vars(Layers.OBS)

        da = obs.copy()
        da.loc[{Dims.CELLS: cells_selected, Dims.FEATURES: Features.LABELS}] = label_id

        # update the graph
        graph.add_node(
            label_id,
            label_id=label_id,
            label_name=label_names[label_id],
            channel=channel,
            threshold=threshold,
            intensity_key=intensity_key,
            override=override,
            step=step,
            num_cells=len(cells_gated),
        )
        graph.add_edge(parent, label_id)

        # save graph to the image container
        # TODO: Refactor this
        obj.attrs["graph"] = nx.to_dict_of_dicts(graph)
        for node_prop in [
            "channel",
            "threshold",
            "intensity_key",
            "override",
            "label_name",
            "label_id",
            "step",
            "num_cells",
        ]:
            obj.attrs[node_prop] = nx.get_node_attributes(graph, node_prop)

        # if len(self._obj.attrs) == 0:
        #     # initialize graph
        #     graph = nx.Graph()
        #     graph.add_node(0)
        #     graph.add_node(
        #         label_id, channel=channel, threshold=threshold, intensity_key=intensity_key, override=override
        #     )
        #     graph.add_edge(0, label_id)

        #     obj.attrs["graph"] = nx.to_dict_of_dicts(graph)
        #     for node_prop in ["channel", "threshold", "intensity_key", "override"]:
        #         obj.attrs[node_prop] = nx.get_node_attributes(graph, node_prop)
        #
        # else:
        #     graph = nx.from_dict_of_dicts(obj.attrs.pop("graph"))

        #     for node_prop in ["channel", "threshold", "intensity_key", "override"]:
        #         nx.set_node_attributes(graph, obj.attrs.pop(node_prop), node_prop)

        #     graph.add_node(
        #         label_id, channel=channel, threshold=threshold, intensity_key=intensity_key, override=override
        #     )
        #     graph.add_edge(parent, label_id)

        return xr.merge([obj, da])

    def add_label_types_from_dataframe(
        self,
        df: pd.DataFrame,
        cell_col: str = "cell",
        label_col: str = "label",
        colors: Union[list, None] = None,
        names: Union[list, None] = None,
    ):
        sub = df.loc[:, [cell_col, label_col]].dropna()

        cells = sub.loc[:, cell_col].values.squeeze()
        labels = sub.loc[:, label_col].values.squeeze()

        assert ~np.all(labels < 0), "Labels must be >= 0."

        formated_labels = _format_labels(labels)
        unique_labels = np.unique(formated_labels)

        if np.all(formated_labels == labels):
            da = xr.DataArray(
                formated_labels.reshape(-1, 1),
                coords=[cells, [Features.LABELS]],
                dims=[Dims.CELLS, Dims.FEATURES],
                name=Layers.OBS,
            )
        else:
            da = xr.DataArray(
                np.stack([formated_labels, labels], -1),
                coords=[
                    cells,
                    [
                        Features.LABELS,
                        Features.ORIGINAL_LABELS,
                    ],
                ],
                dims=[Dims.CELLS, Dims.FEATURES],
                name=Layers.OBS,
            )

        da = da.where(
            da.coords[Dims.CELLS].isin(
                self._obj.coords[Dims.CELLS],
            ),
            drop=True,
        )

        self._obj = xr.merge([self._obj.sel(cells=da.cells), da])

        if colors is not None:
            assert len(colors) == len(unique_labels), "Colors has the same."
        else:
            colors = np.random.choice(COLORS, size=len(unique_labels), replace=False)

        self._obj = self._obj.la.add_label_property(colors, Props.COLOR)

        if names is not None:
            assert len(names) == len(unique_labels), "Names has the same."
        else:
            names = [f"Cell type {i+1}" for i in range(len(unique_labels))]

        self._obj = self._obj.la.add_label_property(names, Props.NAME)
        self._obj[Layers.SEGMENTATION].values = _remove_unlabeled_cells(
            self._obj[Layers.SEGMENTATION].values, self._obj.coords[Dims.CELLS].values
        )

        return self._obj

    def add_label_property(self, array: Union[np.ndarray, list], prop: str):
        unique_labels = np.unique(self._obj[Layers.OBS].sel({Dims.FEATURES: Features.LABELS}))

        if type(array) is list:
            array = np.array(array)

        da = xr.DataArray(
            array.reshape(-1, 1),
            coords=[unique_labels.astype(int), [prop]],
            dims=[Dims.LABELS, Dims.PROPS],
            name=Layers.LABELS,
        )

        if Layers.LABELS in self._obj:
            da = xr.concat(
                [self._obj[Layers.LABELS], da],
                dim=Dims.PROPS,
            )

        return xr.merge([da, self._obj])

    def set_label_name(self, label, name):
        self._obj[Layers.LABELS].loc[label, Props.NAME] = name

    def set_label_color(self, label, color):
        self._obj[Layers.LABELS].loc[label, Props.COLOR] = color

    def render_segmentation(
        self,
        alpha=0,
        alpha_boundary=1,
        mode="inner",
    ):
        color_dict = {1: "white"}
        cmap = _get_listed_colormap(color_dict)
        segmentation = self._obj[Layers.SEGMENTATION].values
        segmentation = _remove_segmentation_mask_labels(segmentation, self._obj.coords[Dims.CELLS].values)
        # mask = _label_segmentation_mask(segmentation, cells_dict)

        if Layers.PLOT in self._obj:
            attrs = self._obj[Layers.PLOT].attrs
            rendered = _render_label(
                segmentation,
                cmap,
                self._obj[Layers.PLOT].values,
                alpha=alpha,
                alpha_boundary=alpha_boundary,
                mode=mode,
            )
            self._obj = self._obj.drop_vars(Layers.PLOT)
        else:
            attrs = {}
            rendered = _render_label(
                segmentation,
                cmap,
                alpha=alpha,
                alpha_boundary=alpha_boundary,
                mode=mode,
            )

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

    def render_label(self, alpha=0, alpha_boundary=1, mode="inner", override_color=None):
        assert Layers.LABELS in self._obj, "Add labels via the add_labels function first."

        # TODO: Attribute class in constants.py
        color_dict = self._label_to_dict(Props.COLOR, relabel=True)
        if override_color is not None:
            color_dict = {k: override_color for k in color_dict.keys()}

        cmap = _get_listed_colormap(color_dict)

        cells_dict = self._cells_to_label(relabel=True)
        segmentation = self._obj[Layers.SEGMENTATION].values
        mask = _label_segmentation_mask(segmentation, cells_dict)

        if Layers.PLOT in self._obj:
            attrs = self._obj[Layers.PLOT].attrs
            rendered = _render_label(
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
            rendered = _render_label(mask, cmap, alpha=alpha, alpha_boundary=alpha_boundary, mode=mode)

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

    def neighborhood_graph(self, neighbors=10, radius=1.0, metric="euclidean"):
        cell_coords = self._obj.coords[Dims.CELLS].values

        # fit neighborhood tree
        tree = NearestNeighbors(n_neighbors=neighbors, radius=radius, metric=metric)
        coords = self._obj[Layers.OBS].loc[:, [Features.X, Features.Y]].values
        tree.fit(coords)
        distances, nearest_neighbors = tree.kneighbors()

        #
        da = xr.DataArray(
            cell_coords[nearest_neighbors],
            coords=[
                self._obj.coords[Dims.CELLS],
                np.arange(neighbors),
            ],
            dims=[Dims.CELLS, Dims.NEIGHBORS],
            name=Layers.NEIGHBORS,
        )

        return xr.merge([self._obj, da])

    # def add_labels(
    #     self,
    #     labels,
    #     cell_col: str = "cell",
    #     label_col: str = "label",
    #     color_dict: Union[None, dict] = None,
    #     names_dict: Union[None, dict] = None,
    # ):
    #     num_cells = self._obj.dims[Dims.CELLS]

    #     # select the cells indices which are consistent with the segmentation
    #     df = (
    #         pd.DataFrame(index=self._obj.coords[Dims.CELLS].values)
    #         .reset_index()
    #         .rename(columns={"index": cell_col})
    #     )

    #     df = df.merge(labels, on=cell_col, how="inner")

    #     array = df.loc[:, label_col].values

    #     if 0 in array:
    #         logger.warning(
    #             "Found '0' as cell type as label, reindexing. Please ensure that cell type labels are consecutive integers (1, 2, ..., k) starting from 1."
    #         )
    #         array += 1

    #     unique_labels = np.unique(array)
    #     attrs = {}

    #     # set up the meta data
    #     if color_dict is None:
    #         logger.warning("No label colors specified. Choosing random colors.")
    #         attrs[Attrs.LABEL_COLORS] = {
    #             k: v
    #             for k, v in zip(
    #                 unique_labels,
    #                 np.random.choice(COLORS, size=len(unique_labels), replace=False),
    #             )
    #         }
    #     else:
    #         attrs[Attrs.LABEL_COLORS] = color_dict

    #     if names_dict is None:
    #         attrs[Attrs.LABEL_NAMES] = {k: f"Cell type {k}" for k in unique_labels}
    #     else:
    #         attrs[Attrs.LABEL_NAMES] = names_dict

    #     da = xr.DataArray(
    #         array.reshape(-1, 1),
    #         coords=[df.loc[:, cell_col].values, ["label"]],
    #         dims=[Dims.CELLS, Dims.LABELS],
    #         name=Layers.LABELS,
    #         attrs=attrs,
    #     )

    #     # merge datasets
    #     ds = self._obj.merge(da, join="inner")
    #     ds.se._remove_unlabeled_cells()

    #     lost_cells = num_cells - ds.dims[Dims.CELLS]

    #     if lost_cells > 0:
    #         logger.warning(f"No cell label for {lost_cells} cells. Dropping cells.")

    #     return ds
