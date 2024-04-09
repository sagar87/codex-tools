from typing import Callable, List, Union

import networkx as nx
import numpy as np
import xarray as xr
from skimage.segmentation import relabel_sequential
from sklearn.neighbors import NearestNeighbors

from ..base_logger import logger
from ..constants import Dims, Features, Layers, Props

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


@xr.register_dataset_accessor("la")
class LabelAccessor:
    def __init__(self, xarray_obj):
        self._obj = xarray_obj

    def __contains__(self, key):
        if Layers.LABELS not in self._obj:
            return False

        label_dict = self._obj.la._label_to_dict(Props.NAME)
        return key in label_dict.keys() or key in label_dict.values()

    def _relabel_dict(self, dictionary: dict):
        _, fw, _ = relabel_sequential(self._obj.coords[Dims.LABELS].values)
        return {fw[k]: v for k, v in dictionary.items()}

    def _label_to_dict(self, prop: str, reverse: bool = False, relabel: bool = False) -> dict:
        """Returns a dictionary that maps each label to a list to their property.

        Parameters
        ----------
        prop : str
            The property to map to the labels.
        reverse : bool
            If True, the dictionary will be reversed.
        relabel : bool
            Deprecated.

        Returns
        -------
        label_dict : dict
            A dictionary that maps each label to a list to their property.
        """
        labels_layer = self._obj[Layers.LABELS]
        labels = self._obj.coords[Dims.LABELS]
        # print(labels)
        # print(labels_layer.loc[labels[1], prop])
        label_dict = {}

        for label in labels:
            # print(label)
            current_row = labels_layer.loc[label, prop]
            label_dict[label.values.item()] = current_row.values.item()

        # label_dict = {label.item(): labels_layer.loc[label, prop].item() for label in self._obj.coords[Dims.LABELS]}

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

    def _label_name_to_id(self, label):
        """Given a label name return its id."""
        label_names_reverse = self._obj.la._label_to_dict(Props.NAME, reverse=True)
        if label not in label_names_reverse:
            raise ValueError(f"Cell type {label} not found.")

        return label_names_reverse[label]

    def filter_by_obs(self, col: str, func: Callable):
        """Returns the list of cells with the labels from items."""
        cells = self._obj[Layers.OBS].sel({Dims.FEATURES: col}).values.copy()
        cells_bool = func(cells)
        cells_sel = self._obj.coords[Dims.CELLS][cells_bool].values
        # print(cells_sel, len(cells_sel))
        return self._obj.sel({Dims.CELLS: cells_sel})

    def filter_by_intensity(self, col: str, func: Callable, layer_key: str):
        """Returns the list of cells with the labels from items."""
        cells = self._obj[layer_key].sel({Dims.CHANNELS: col}).values.copy()
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
        """
        Deselect specific label indices from the data object.

        This method deselects specific label indices from the data object, effectively removing them from the selection.
        The deselection can be performed using slices, lists, tuples, or individual integers.

        Parameters
        ----------
        indices : slice, list, tuple, or int
            The label indices to be deselected. Can be a slice, list, tuple, or an individual integer.

        Returns
        -------
        any
            The updated data object with the deselected label indices.

        Notes
        -----
        - The function uses 'indices' to specify which labels to deselect.
        - 'indices' can be provided as slices, lists, tuples, or an integer.
        - The function then updates the data object to remove the deselected label indices.
        """
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

    def add_label_type(self, name: str, color: str = "w") -> xr.Dataset:
        """
        Add a new label type to the data object.

        This method adds a new label type with the specified 'name' and 'color' to the data object.
        The label type is used to identify and categorize cells in the segmentation mask.

        Parameters
        ----------
        name : str
            The name of the new label type to be added.
        color : str, optional
            The color code to represent the new label type in the visualization. Default is "white" ("w").

        Returns
        -------
        xr.Dataset
            The updated data object with the newly added label type.

        Raises
        ------
        ValueError
            If the segmentation mask or observation table is not found in the data object.
            If the provided 'name' already exists as a label type.

        Notes
        -----
        - The function checks for the existence of the segmentation mask and observation table in the data object.
        - It ensures that the 'name' of the new label type does not already exist in the label types.
        - The function then adds the new label type with the given 'name' and 'color' to the data object.
        """

        if Layers.SEGMENTATION not in self._obj:
            raise ValueError("No segmentation mask found.")
        if Layers.OBS not in self._obj:
            raise ValueError("No observation table found.")

        # Assert that label type is not already present
        if Layers.LABELS in self._obj:
            if name in self._obj[Layers.LABELS].sel({Dims.PROPS: Props.NAME}):
                raise ValueError("Label type already exists.")

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

    def get_gate_graph(self, pop: bool = False) -> nx.DiGraph:
        """
        Get the gating graph from the data object.

        This method retrieves the gating graph from the data object, which represents the gating hierarchy
        used to categorize cells into different cell types.

        Parameters
        ----------
        pop : bool, optional
            Whether to remove the gating graph from the data object after retrieval. Default is False.

        Returns
        -------
        networkx.DiGraph
            The gating graph representing the gating hierarchy of cell types.

        Notes
        -----
        - The function looks for the 'graph' attribute in the data object to obtain the gating graph.
        - If 'pop' is True, the gating graph is removed from the data object after retrieval.
        """
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
                num_cells=self._obj.dims[Dims.CELLS],
                gated_cells=set(self._obj.coords[Dims.CELLS].values),
            )

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

    def remove_label_type(self, cell_type: Union[int, List[int]]) -> xr.Dataset:
        """
        Remove specific cell type label(s) from the data object.

        This method removes specific cell type label(s) identified by 'cell_type' from the data object.
        The cell type label(s) are effectively removed, and their associated cells are assigned to the 'Unlabeled' category.

        Parameters
        ----------
        cell_type : int or list of int
            The ID(s) of the cell type label(s) to be removed.

        Returns
        -------
        xr.Dataset
            The updated data object with the specified cell type label(s) removed.

        Raises
        ------
        ValueError
            If the data object does not contain any cell type labels.
            If the specified 'cell_type' is not found among the existing cell type labels.

        Notes
        -----
        - The function first checks for the existence of cell type labels in the data object.
        - It then removes the specified 'cell_type' from the cell type labels, setting their cells to the 'Unlabeled' category.
        """
        if isinstance(cell_type, int):
            cell_type = [cell_type]

        if isinstance(cell_type, str):
            cell_type = [self._obj.la._label_name_to_id(cell_type)]
        # TODO: If list should properly get cell -type
        # TODO: should call reset label type prior to removing the cell type

        if Layers.LABELS not in self._obj:
            raise ValueError("No cell type labels found.")

        for i in cell_type:
            if i not in self._obj.coords[Dims.LABELS].values:
                raise ValueError(f"Cell type {i} not found.")

        cells_bool = (self._obj[Layers.OBS].sel({Dims.FEATURES: Features.LABELS}) == cell_type).values
        cells = self._obj.coords[Dims.CELLS][cells_bool].values

        self._obj[Layers.OBS].loc[{Dims.FEATURES: Features.LABELS, Dims.CELLS: cells}] = 0

        return self._obj.sel({Dims.LABELS: [i for i in self._obj.coords[Dims.LABELS] if i not in cell_type]})

    def reset_label_type(self, label_id) -> xr.Dataset:
        """
        Reset the label type of cells to its parent label.

        This method resets the label type of cells, identified by the given label_id, to its parent label.
        The cells assigned to descendant labels of the provided label_id will also be updated to the parent label.

        Parameters
        ----------
        label_id :
            The cell type id or name to reset its cells' label type.

        Returns
        -------
        xr.Dataset
            The updated data object with cells' label type reset to its parent label.

        Raises
        ------
        ValueError
            If the provided label_id is not found in the data object.

        Notes
        -----
        - The function identifies the parent label of the provided label_id.
        - It gathers all the descendant labels of the provided label_id, including itself.
        - The cells assigned to the descendant labels will be updated to the parent label.
        - The function also updates the gating graph and relevant attributes in the data object.
        """

        labels = self._obj.coords[Dims.LABELS]
        label_names_reverse = self._obj.la._label_to_dict(Props.NAME, reverse=True)

        if isinstance(label_id, str):
            if label_id not in label_names_reverse:
                raise ValueError(f"Cell type {label_id} not found.")

            # overwrite label_id with the corresponding id
            label_id = label_names_reverse[label_id]

        if label_id not in labels:
            raise ValueError(f"Cell type id {label_id} not found.")

        graph = self._obj.la.get_gate_graph(pop=False)
        gated_cells = nx.get_node_attributes(graph, "gated_cells")

        descendants = sorted(nx.descendants(graph, label_id) | {label_id})
        # if label_id == 2:
        #     import pdb

        #     pdb.set_trace()

        cells_selected = []

        for node in descendants:
            cells_selected.append(gated_cells[node])

        cells_selected = np.concatenate(cells_selected)

        predecessor = [key for key in graph.predecessors(label_id)]
        parent_id = predecessor[-1]

        obs = self._obj[Layers.OBS]
        obj = self._obj.drop_vars(Layers.OBS)

        da = obs.copy()
        da.loc[{Dims.CELLS: cells_selected, Dims.FEATURES: Features.LABELS}] = parent_id

        updated_obj = xr.merge([obj, da])
        updated_labels = updated_obj.la._cells_to_label(include_unlabeled=True)
        updated_labels = {k: v for k, v in updated_labels.items() if len(v) != 0}
        updated_label_counts = {k: len(v) for k, v in updated_labels.items()}
        color_dict = self._obj.la._label_to_dict(Props.COLOR)

        for node in descendants:
            graph.remove_node(node)

        updated_obj.attrs["graph"] = nx.to_dict_of_dicts(graph)
        updated_obj.attrs["num_cells"] = updated_label_counts
        updated_obj.attrs["gated_cells"] = updated_labels
        updated_obj.attrs["colors"] = {node: color_dict.get(node, "w") for node in graph.nodes}
        for node_prop in [
            "channel",
            "threshold",
            "intensity_key",
            "override",
            "label_name",
            "label_id",
            "step",
        ]:
            updated_obj.attrs[node_prop] = nx.get_node_attributes(graph, node_prop)

        return updated_obj

    def gate_label_type(
        self,
        label_id: Union[int, str],
        channel: Union[List[str], str],
        threshold: Union[List[float], float],
        intensity_key: str,
        override: bool = False,
        parent: Union[int, str] = 0,
        op: str = "AND",
        show_channel: Union[List[str], str] = None,
    ):
        """
        Gate cells based on specified criteria and assign a cell type label.

        This method gates cells in the data object based on the given channel and threshold.
        Cells that meet the gating criteria will be assigned the provided cell type label.

        Parameters
        ----------
        label_id :
            The cell type id or name to assign to the gated cells.
        channel :
            The channel or list of channels to use for gating.
        threshold :
            The threshold or list of thresholds to use for gating.
        intensity_key :
            The key to use for the intensity layer.
        override : bool, optional
            Whether to override the existing descendant label types. Default is False.
        parent : any, optional
            The parent cell type id or name for gating hierarchy. Default is 0, indicating no parent label.
        op : str, optional
            The logical operator to apply when dealing with multiple channels:
            "AND" for logical AND, "OR" for logical OR. Default is "AND".
        show_channel : any, optional
            The channel or list of channels to display in the gating result.
            If None, the gating channel(s) will be used. Default is None.

        Returns
        -------
        any
            The updated data object with gated cells labeled with the specified cell type.

        Raises
        ------
        ValueError
            If the provided label_id or parent is not found in the data object.
        ValueError
            If the threshold array length does not match the number of channels.
        ValueError
            If the logical operator (op) is neither "AND" nor "OR".

        Notes
        -----
        - The gating process is based on the specified channel(s) and threshold(s).
        - The result of the gating operation is stored as new cell type labels.
        - The gating operation can either override existing descendant labels or not.
        - The gating process also updates the gating graph and relevant attributes in the data object.
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

        if isinstance(channel, list):
            num_channels = len(channel)
            if isinstance(threshold, float) and num_channels > 1:
                logger.warning("Caution, found more than 1 channel but only one threshold. Broadcasting.")
                threshold = np.array([threshold] * num_channels).reshape(1, num_channels)
            if isinstance(threshold, list):
                if len(threshold) > num_channels or len(threshold) < num_channels:
                    raise ValueError("Threshold array must have the same length as the number of channels.")

                threshold = np.array(threshold).reshape(1, num_channels)

        if isinstance(channel, str):
            channel = [channel]
        if isinstance(threshold, float):
            threshold = np.array(threshold).reshape(1, 1)

        label_names = self._obj.la._label_to_dict(Props.NAME)  # dict of label names per label id
        labeled_cells = self._obj.la._cells_to_label(include_unlabeled=True)  # dict of cell ids per label
        graph = self._obj.la.get_gate_graph(pop=False)  # gating graph
        step = max(list(nx.get_node_attributes(graph, "step").values())) + 1  # keeps track of the current gating step

        # should use filter
        cells_bool = (self._obj[intensity_key].sel({Dims.CHANNELS: channel}) > threshold).values

        if cells_bool.squeeze().ndim > 1:
            if op == "AND":
                cells_bool = np.all(cells_bool, axis=1)
            elif op == "OR":
                cells_bool = np.any(cells_bool, axis=1)
            else:
                raise ValueError("Operator (op) must  be either AND or OR.")

        cells = self._obj.coords[Dims.CELLS].values
        cells_gated = cells[cells_bool.squeeze()]

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

        obs = self._obj[Layers.OBS]
        obj = self._obj.drop_vars(Layers.OBS)

        da = obs.copy()
        da.loc[{Dims.CELLS: cells_selected, Dims.FEATURES: Features.LABELS}] = label_id

        updated_obj = xr.merge([obj, da])
        updated_labels = updated_obj.la._cells_to_label(include_unlabeled=True)
        updated_labels = {k: v for k, v in updated_labels.items() if len(v) != 0}
        updated_label_counts = {k: len(v) for k, v in updated_labels.items()}
        color_dict = self._obj.la._label_to_dict(Props.COLOR)

        # update the graph
        graph.add_node(
            label_id,
            label_id=label_id,
            label_name=label_names[label_id],
            parent=parent,
            channel=channel,
            threshold=threshold.squeeze().tolist(),
            intensity_key=intensity_key,
            override=override,
            step=step,
            op=op,
            show_channel=show_channel if show_channel is not None else channel,
        )
        graph.add_edge(parent, label_id)

        # save graph to the image container
        # TODO: Refactor this

        updated_obj.attrs["graph"] = nx.to_dict_of_dicts(graph)
        updated_obj.attrs["num_cells"] = updated_label_counts
        updated_obj.attrs["gated_cells"] = updated_labels
        updated_obj.attrs["colors"] = {node: color_dict.get(node, "w") for node in graph.nodes}

        for node_prop in [
            "channel",
            "threshold",
            "intensity_key",
            "override",
            "label_name",
            "label_id",
            "step",
            "op",
            "parent",
            "show_channel",
        ]:
            updated_obj.attrs[node_prop] = nx.get_node_attributes(graph, node_prop)

        return updated_obj

    def add_label_types_from_graph(self, graph):
        """
        Add label types and gate cells based on the provided gating graph.

        This method adds label types to the data object based on the information in the provided gating graph.
        It also gates cells for each step in the graph, applying the specified criteria from the graph.

        Parameters
        ----------
        graph : networkx.DiGraph
            The gating graph representing cell type hierarchies and gating steps.

        Returns
        -------
        any
            The updated data object with added label types and gated cells.

        Notes
        -----
        - The function extracts relevant information from the gating graph, including label names, colors,
        gating channels, thresholds, intensity keys, logical operators, parent labels, and override flags.
        - It iterates over the steps in the graph and adds label types for each unique cell type encountered.
        - For each step, the function gates cells based on the provided gating criteria for the respective cell type.
        - The gating process updates the data object with the newly added label types and gated cells.
        - The function assumes that the data object (`self._obj`) has relevant methods for adding label types
        (`add_label_type`) and gating cells (`gate_label_type`) based on its existing implementation.
        """
        # unpack data
        steps = {v: k for k, v in nx.get_node_attributes(graph, "step").items()}
        label_names = nx.get_node_attributes(graph, "label_name")
        channels = nx.get_node_attributes(graph, "channel")
        colors = nx.get_node_attributes(graph, "colors")
        parents = nx.get_node_attributes(graph, "parent")
        ops = nx.get_node_attributes(graph, "op")
        override = nx.get_node_attributes(graph, "override")
        intensity_channels = nx.get_node_attributes(graph, "intensity_key")
        thresholds = nx.get_node_attributes(graph, "threshold")

        for step, cell_type in steps.items():
            if step == 0:
                continue

            current_name = label_names[cell_type]
            current_color = colors[cell_type]
            current_channels = channels[cell_type]
            current_thresholds = thresholds[cell_type]
            current_key = intensity_channels[cell_type]
            current_override = override[cell_type]
            current_parent = parents[cell_type]
            current_op = ops[cell_type]

            if current_name not in self._obj.la:
                self._obj = self._obj.la.add_label_type(current_name, current_color)

            self._obj = self._obj.la.gate_label_type(
                current_name,
                current_channels,
                current_thresholds,
                current_key,
                current_override,
                current_parent,
                current_op,
            )
        return self._obj

    def add_label_property(self, array: Union[np.ndarray, list], prop: str):
        """
        Add a label property for each unique cell type label.

        This method adds a property, specified by 'prop', for each unique cell type label in the data object.
        The property values are taken from the 'array' argument and assigned to each corresponding cell type label.

        Parameters
        ----------
        array : numpy.ndarray or list
            An array or list containing property values to be assigned to each unique cell type label.
        prop : str
            The name of the property to be added to the cell type labels.

        Returns
        -------
        any
            The updated data object with the added label property.

        Notes
        -----
        - The function ensures that 'array' is converted to a NumPy array.
        - It creates a DataArray 'da' with the given 'array' as the property values and unique cell type labels as coords.
        - The DataArray 'da' is then merged into the data object, associating properties with cell type labels.
        - If the label property already exists in the data object, it will be updated with the new property values.
        """
        unique_labels = self._obj.coords[
            Dims.LABELS
        ].values  # np.unique(self._obj[Layers.OBS].sel({Dims.FEATURES: Features.LABELS}))

        if type(array) is list:
            array = np.array(array)

        da = xr.DataArray(
            array.reshape(-1, 1),
            coords=[unique_labels.astype(int), [prop]],
            dims=[Dims.LABELS, Dims.PROPS],
            name=Layers.LABELS,
        )

        if Layers.LABELS in self._obj:
            # import pdb;pdb.set_trace()
            da = xr.concat(
                [self._obj[Layers.LABELS], da],
                dim=Dims.PROPS,
            )

        return xr.merge([da, self._obj])

    def set_label_name(self, label, name):
        """
        Set the name of a specific cell type label.

        This method sets the 'name' of a specific cell type label identified by the 'label'.
        The 'label' can be either a label ID or the name of the cell type label.

        Parameters
        ----------
        label : int or str
            The ID or name of the cell type label whose name will be updated.
        name : str
            The new name to be assigned to the specified cell type label.

        Returns
        -------
        None

        Notes
        -----
        - The function converts the 'label' from its name to the corresponding ID for internal processing.
        - It updates the name of the cell type label in the data object to the new 'name'.
        """
        if isinstance(label, str):
            label = self._obj.la._label_name_to_id(label)

        self._obj[Layers.LABELS].loc[label, Props.NAME] = name

    def set_label_color(self, label, color):
        """
        Set the color of a specific cell type label.

        This method sets the 'color' of a specific cell type label identified by the 'label'.
        The 'label' can be either a label ID or the name of the cell type label.

        Parameters
        ----------
        label : int or str
            The ID or name of the cell type label whose color will be updated.
        color : any
            The new color to be assigned to the specified cell type label.

        Returns
        -------
        None

        Notes
        -----
        - The function converts the 'label' from its name to the corresponding ID for internal processing.
        - It updates the color of the cell type label in the data object to the new 'color'.
        """
        if isinstance(label, str):
            label = self._obj.la._label_name_to_id(label)

        self._obj[Layers.LABELS].loc[label, Props.COLOR] = color

    def neighborhood_graph(self, neighbors=10, radius=1.0, metric="euclidean"):
        """
        Generate a neighborhood graph based on cell coordinates.

        This method creates a neighborhood graph for the cells in the data object based on their coordinates.
        The neighborhood graph contains information about the 'neighbors' nearest cells to each cell.

        Parameters
        ----------
        neighbors : int, optional
            The number of neighbors to consider for each cell. Default is 10.
        radius : float, optional
            The radius within which to search for neighbors. Default is 1.0.
        metric : str, optional
            The distance metric to be used when calculating distances between cells. Default is "euclidean".

        Returns
        -------
        any
            The updated data object with the neighborhood graph information.

        Notes
        -----
        - The function extracts cell coordinates from the data object.
        - It uses the 'neighbors', 'radius', and 'metric' parameters to generate the neighborhood graph.
        - The neighborhood graph information is added to the data object as a new layer.
        """
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
