from typing import List

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, ListedColormap
from skimage.measure import label, regionprops
from skimage.morphology import closing, square
from skimage.segmentation import clear_border, find_boundaries

from ..pp.utils import _normalize


def _get_linear_colormap(palette: list, background: str = "black"):
    """
    Create a list of linear segmented colormaps based on the given palette.

    Parameters:
    ----------
    palette : list
        A list of colors representing the desired palette.
    background : str, optional
        The background color for the colormaps. Default is 'black'.

    Returns:
    -------
    list
        A list of LinearSegmentedColormap objects.
    """
    return [LinearSegmentedColormap.from_list(color, [background, color], N=256) for color in palette]


def _get_listed_colormap(palette: dict):
    """
    Create a ListedColormap object based on the provided palette. The palette should map from cell type IDs to colors, e. g. {1: 'red', 2: 'green', ...}

    Parameters:
    -----------
    palette : dict
        A dictionary containing the cell type labels as keys and the corresponding colors as values.

    Returns:
    --------
    cmap : ListedColormap
        The created ListedColormap object.

    Notes:
    ------
    - If the palette does not contain the label 0, a black background color will be added.
    - The number of colors in the colormap will be equal to the number of labels in the palette.
    """
    sorted_labels = sorted(palette.keys())
    colors = [palette[k] for k in sorted_labels]

    # adding black background if we don't have any unlabeled (0) cells
    if 0 in sorted_labels:
        cmap = ListedColormap(colors, N=len(colors))
    else:
        cmap = ListedColormap(["black"] + colors, N=len(colors) + 1)

    return cmap


def _colorize(
    img: np.ndarray,
    colors: List[str] = ["C1", "C2", "C3", "C4", "C5"],
    background: str = "black",
    normalize: bool = True,
) -> np.ndarray:
    """
    Apply colorization to an image based on a given colors.

    Parameters:
        img (np.ndarray): The input image to be colorized.
        colors (List[str], optional): The list of colors to be used for colorization. Defaults to ["C1", "C2", "C3", "C4", "C5"].
        background (str, optional): The background color. Defaults to "black".
        normalize (bool, optional): Whether to normalize the image before colorization. Defaults to True.

    Returns:
        np.ndarray: The colorized image.

    Raises:
        AssertionError: If the length of the palette is less than the number of channels in the image.
    """

    num_channels = img.shape[0]

    assert (
        len(colors) >= num_channels
    ), "Length of colors must at least be greater or equal the number of channels of the image."

    cmaps = _get_linear_colormap(colors[:num_channels], background)

    if normalize:
        img = _normalize(img)

    colored = np.stack([cmaps[i](img[i]) for i in range(num_channels)], 0)

    return colored


def _render_segmentation(
    segmentation: np.ndarray,
    colors: List[str],
    background: str = "black",
    img: np.ndarray = None,
    alpha: float = 0.2,
    alpha_boundary: float = 1.0,
    mode: str = "inner",
) -> np.ndarray:
    """
    Render a 2D or 3D (in the case of multiple segmentations, e. g. with cellpose) segmentation.

    Parameters:
        segmentation (np.ndarray): The segmentation array with shape (num_channels, height, width).
        colors (List[str]): The list of colors to be applied to each channel of the segmentation.
        background (str, optional): The background color. Defaults to "black".
        img (np.ndarray, optional): The image to be used as a base for rendering. Defaults to None.
        alpha (float, optional): The transparency level for the colored segmentation. Defaults to 0.2.
        alpha_boundary (float, optional): The transparency level for the boundary of the segmentation. Defaults to 1.0.
        mode (str, optional): The mode for finding boundaries. Defaults to "inner".

    Returns:
        np.ndarray: The rendered image with shape (num_channels, height, width, rgba).

    """
    num_channels = segmentation.shape[0]
    cmaps = _get_linear_colormap(colors[:num_channels], background)
    # transforming the segmentation into dtype float (otherwise it is not rendered for some reason)
    segmentation = segmentation.astype(np.float32)

    colored_segmentation = np.stack([cmaps[i](segmentation[i]) for i in range(num_channels)], 0)

    mask_bool = segmentation > 0
    # find_boundaries only operates on single-channel images, hence we need to construct the boundary image for each channel separately
    bounds = np.array([find_boundaries(segmentation[i, :, :], mode=mode) for i in range(num_channels)])
    mask_bound = np.bitwise_and(mask_bool, bounds)

    if img is None:
        img = np.zeros(colored_segmentation.shape, np.float32)
        img[..., -1] = 1

    # if a plot is already provided, we need to copy it n_marker times to apply the masking operations later
    # intensities are normalized by n_channels to avoid overexposure
    if len(img.shape) == 3:
        img = np.repeat(img[np.newaxis, :, :, :], num_channels, axis=0) / num_channels

    im = img.copy()

    im[mask_bool] = alpha * colored_segmentation[mask_bool] + (1 - alpha) * img[mask_bool]
    im[mask_bound] = alpha_boundary * colored_segmentation[mask_bound] + (1 - alpha_boundary) * img[mask_bound]

    return im


def _render_labels(
    segmentation: np.ndarray,
    cmap: list,
    img: np.ndarray = None,
    alpha: float = 0.2,
    alpha_boundary: float = 1.0,
    mode: str = "inner",
) -> np.ndarray:
    """
    Render labels on an image.

    Parameters:
    - segmentation (np.ndarray): The segmentation array containing labels.
    - cmap (list): The color map used to map labels to colors. Should be computed with _get_listed_colormap().
    - img (np.ndarray, optional): The image on which to render the labels. If not provided, a blank image will be created.
    - alpha (float, optional): The transparency of the labels. Default is 0.2.
    - alpha_boundary (float, optional): The transparency of the label boundaries. Default is 1.0.
    - mode (str, optional): The mode used to find boundaries. Default is "inner".

    Returns:
    - np.ndarray: The image with labels rendered.
    """
    colored_mask = cmap(segmentation)

    mask_bool = segmentation > 0
    mask_bound = np.bitwise_and(mask_bool, find_boundaries(segmentation, mode=mode))

    if img is None:
        img = np.zeros(segmentation.shape + (4,), np.float32)
        img[..., -1] = 1

    im = img.copy()

    im[mask_bool] = alpha * colored_mask[mask_bool] + (1 - alpha) * img[mask_bool]
    im[mask_bound] = alpha_boundary * colored_mask[mask_bound] + (1 - alpha_boundary) * img[mask_bound]

    return im


def _label_segmentation_mask(segmentation: np.ndarray, ct_to_cells_dict: dict) -> np.ndarray:
    """
    Label the segmentation mask based on the provided celltype-to-cells dictionary.

    Parameters
    ----------
    segmentation : np.ndarray
        The segmentation mask as a numpy array.
    ct_to_cells_dict : dict
        A dictionary mapping each cell type ID (1, 2, ...) to a list of cell IDs. E. g. {1: [1, 2, 3, 4], ...}.
        Can be computed with la._cells_to_label().

    Returns
    -------
    np.ndarray
        The labeled segmentation mask where each cell is assigned a cell type label.
    """
    labeled_segmentation = segmentation.copy()
    all_cells = []

    for k, v in ct_to_cells_dict.items():
        mask = np.isin(segmentation, v)
        labeled_segmentation[mask] = k
        all_cells.extend(v)

    # remove cells that are not indexed
    neg_mask = ~np.isin(segmentation, all_cells)
    labeled_segmentation[neg_mask] = 0

    return labeled_segmentation


def _set_up_subplots(num_plots: int = 1, ncols: int = 4, width: int = 4, height: int = 3):
    """
    Set up subplots for plotting multiple figures.

    Parameters:
    - num_plots (int): The number of plots to be displayed.
    - ncols (int): The number of columns in the subplot grid.
    - width (int): The width of each subplot figure.
    - height (int): The height of each subplot figure.

    Returns:
    - fig: The matplotlib figure object.
    - axes: The axes objects for the subplots.

    If `num_plots` is 1, a single subplot is created and returned.
    If `num_plots` is greater than 1, a grid of subplots is created with the specified number of columns (`ncols`).
    The number of rows (`nrows`) is calculated based on the number of plots and the number of columns.
    The size of each subplot figure is determined by `width` and `height`.
    The excess subplots beyond `num_plots` are turned off to hide them.
    """
    if num_plots == 1:
        fig, ax = plt.subplots()
        return fig, ax

    nrows, reminder = divmod(num_plots, ncols)

    if num_plots < ncols:
        nrows = 1
        ncols = num_plots
    else:
        nrows, reminder = divmod(num_plots, ncols)

        if nrows == 0:
            nrows = 1
        if reminder > 0:
            nrows += 1

    fig, axes = plt.subplots(nrows, ncols, figsize=(width * ncols, height * nrows))
    _ = [ax.axis("off") for ax in axes.flatten()[num_plots:]]
    return fig, axes


def _autocrop(img: np.ndarray, padding: int = 50, downsample: int = 10):
    """
    Crop an image based on the regions of interest so that the background around the tissue/TMA gets cropped away.

    Parameters:
        img (np.ndarray): The input image as a NumPy array.
        padding (int, optional): The padding to be added around the cropped image in pixels. Defaults to 50.
        downsample (int, optional): The downsample factor to be used for the cropping. Defaults to 10.

    Returns:
        tuple: A tuple containing two slices representing the cropped image.
    """

    bw = closing(img > np.quantile(img, 0.8), square(20))
    cleared = clear_border(bw)
    label_image = label(cleared)
    props = regionprops(label_image)

    if len(props) == 0:
        maxr, maxc = img.shape
        minr, minc = 0, 0
        downsample = 1
    else:
        max_idx = np.argmax([p.area for p in props])
        region = props[max_idx]
        minr, minc, maxr, maxc = region.bbox

    return slice(downsample * minc - padding, downsample * maxc + padding), slice(
        downsample * minr - padding, downsample * maxr + padding
    )
