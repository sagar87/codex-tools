from typing import List

import numpy as np
from matplotlib.colors import LinearSegmentedColormap, ListedColormap
from skimage.measure import label, regionprops
from skimage.morphology import closing, square
from skimage.segmentation import clear_border, find_boundaries

from ..constants import Dims
from ..pp.utils import _normalize


def _get_linear_colormap(colors: list, background: str):
    return [LinearSegmentedColormap.from_list(c, [background, c], N=256) for c in colors]


def _colorize(
    img: np.ndarray,
    colors: List[str] = ["C1", "C2", "C3", "C4", "C5"],
    background: str = "black",
    normalize: bool = True,
    name: str = "colored",
) -> np.ndarray:
    """Colorizes a stack of images

    Parameters
    ----------
    dataarray: xr.DataArray
        A xarray DataArray with an image field.
    clors: List[str]
        A list of strings that denote the color of each channel
    background: float
        Background color of the colorized image.
    normalize: bool
        Normalizes the image prior to colorizing it.

    Returns
    -------
    np.ndarray
        A colorized image
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


def _render_labels(mask, cmap_mask, img=None, alpha=0.2, alpha_boundary=1.0, mode="inner"):
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


def _get_listed_colormap(color_dict: dict):
    sorted_labels = sorted(color_dict.keys())
    colors = [color_dict[k] for k in sorted_labels]

    # adding black background if we don't have any unlabeled (0) cells
    if 0 in sorted_labels:
        cmap = ListedColormap(colors, N=len(colors))
    else:
        cmap = ListedColormap(["black"] + colors, N=len(colors) + 1)

    return cmap


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


def _autocrop(sdata, channel=None, downsample=10):
    if channel is None:
        channel = sdata.coords[Dims.CHANNELS].values.tolist()[0]
    image = sdata.pp[channel].pp.downsample(downsample)._image.values.squeeze()

    bw = closing(image > np.quantile(image, 0.8), square(20))
    cleared = clear_border(bw)
    label_image = label(cleared)
    props = regionprops(label_image)
    if len(props) == 0:
        maxr, maxc = image.shape
        minr, minc = 0, 0
        downsample = 1
    else:
        max_idx = np.argmax([p.area for p in props])
        region = props[max_idx]
        minr, minc, maxr, maxc = region.bbox

    return slice(downsample * minc, downsample * maxc), slice(downsample * minr, downsample * maxr)
