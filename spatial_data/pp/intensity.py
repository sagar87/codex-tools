import numpy as np
from scipy.ndimage import binary_erosion, generate_binary_structure, maximum_filter


def sum_intensity(regionmask: np.ndarray, intensity_image: np.ndarray) -> float:
    """
    Calculate the sum of intensity values within the specified regionmask.

    Parameters
    ----------
    regionmask : numpy.ndarray
        Binary mask representing the region of interest.
    intensity_image : numpy.ndarray
        Array containing the intensity values of the corresponding image.

    Returns
    -------
    numpy.float64
        The sum of intensity values within the specified regionmask.
    """
    return np.sum(intensity_image[regionmask])


def mean_intensity(regionmask: np.ndarray, intensity_image: np.ndarray) -> float:
    """
    Calculate the mean of intensity values within the specified regionmask.

    Parameters
    ----------
    regionmask : numpy.ndarray
        Binary mask representing the region of interest.
    intensity_image : numpy.ndarray
        Array containing the intensity values of the corresponding image.

    Returns
    -------
    numpy.float64
        The mean of intensity values within the specified regionmask.
    """
    return np.mean(intensity_image[regionmask])


def arcsinh_mean_intensity(regionmask: np.ndarray, intensity_image: np.ndarray, cofactor: float = 5) -> float:
    """
    Calculate the arcsinh-transformed mean of intensity values within the specified regionmask.

    Parameters
    ----------
    regionmask : numpy.ndarray
        Binary mask representing the region of interest.
    intensity_image : numpy.ndarray
        Array containing the intensity values of the corresponding image.
    cofactor : numpy.float64, optional
        The cofactor used for the arcsinh transformation. Default is 5.

    Returns
    -------
    numpy.float64
        The arcsinh-transformed mean of intensity values within the specified regionmask.
    """
    return np.arcsinh(np.mean(intensity_image[regionmask]) / cofactor)


def arcsinh_median_intensity(regionmask: np.ndarray, intensity_image: np.ndarray, cofactor: float = 5) -> float:
    """
    Calculate the arcsinh-transformed median of intensity values within the specified regionmask.

    Parameters
    ----------
    regionmask : numpy.ndarray
        Binary mask representing the region of interest.
    intensity_image : numpy.ndarray
        Array containing the intensity values of the corresponding image.
    cofactor : numpy.float64, optional
        The cofactor used for the arcsinh transformation. Default is 5.

    Returns
    -------
    numpy.float64
        The arcsinh-transformed median of intensity values within the specified regionmask.
    """
    return np.arcsinh(np.median(intensity_image[regionmask]) / cofactor)


def arcsinh_var_intensity(regionmask: np.ndarray, intensity_image: np.ndarray, cofactor: float = 5) -> float:
    """
    Calculate the arcsinh-transformed variance of intensity values within the specified regionmask.

    Parameters
    ----------
    regionmask : numpy.ndarray
        Binary mask representing the region of interest.
    intensity_image : numpy.ndarray
        Array containing the intensity values of the corresponding image.
    cofactor : numpy.float64, optional
        The cofactor used for the arcsinh transformation. Default is 5.

    Returns
    -------
    numpy.float64
        The arcsinh-transformed variance of intensity values within the specified regionmask.
    """
    return np.arcsinh(np.var(intensity_image[regionmask]) / cofactor)


def arcsinh_sum_intensity(regionmask: np.ndarray, intensity_image: np.ndarray, cofactor: float = 5) -> float:
    """
    Calculate the arcsinh-transformed sum of intensity values within the specified regionmask.

    Parameters
    ----------
    regionmask : numpy.ndarray
        Binary mask representing the region of interest.
    intensity_image : numpy.ndarray
        Array containing the intensity values of the corresponding image.
    cofactor : numpy.float64, optional
        The cofactor used for the arcsinh transformation. Default is 5.

    Returns
    -------
    numpy.float64
        The arcsinh-transformed sum of intensity values within the specified regionmask.
    """
    return np.arcsinh(np.sum(intensity_image[regionmask]) / cofactor)


def is_positive(regionmask: np.ndarray, intensity_image: np.ndarray, threshold: float) -> float:
    """
    Determines whether a cell is positive based on the provided intensity image and threshold.

    Parameters
    ----------
    regionmask : numpy.ndarray
        Binary mask representing the region of interest (ROI) where cells are located.
    intensity_image : numpy.ndarray
        Intensity image representing the fluorescence signal of the cells.
    threshold : float
        Threshold value used for determining positivity. Cells with intensity values greater
        than this threshold are considered positive.

    Returns
    -------
    bool
        A boolean value indicating whether the cell is positive or not. Returns True if the fraction of
        positive pixels within the region of interest exceeds the provided threshold, otherwise returns False.
    """

    return (intensity_image[regionmask] > 0).sum() / (regionmask == 1).sum() > threshold


def percentage_positive(regionmask: np.ndarray, intensity_image: np.ndarray) -> float:
    """
    Computes the percentage of positive pixels per label on the provided intensity image and region mask.

    Parameters
    ----------
    regionmask : numpy.ndarray
        Binary mask representing the region of interest (ROI) where cells are located.
    intensity_image : numpy.ndarray
        Intensity image representing the fluorescence signal of the cells.

    Returns
    -------
    float
        The percentage of positive cells within the region of interest. This is calculated as the ratio of the
        number of positive pixels (intensity greater than 0) to the total number of pixels in the region mask.
    """
    return (intensity_image[regionmask] > 0).sum() / (regionmask == 1).sum()


def detect_peaks_num(regionmask, intensity_image):
    """
    Takes an image and detect the peaks usingthe local maximum filter.
    Returns a boolean mask of the peaks (i.e. 1 when
    the pixel's value is the neighborhood maximum, 0 otherwise)
    """
    image = intensity_image  # [regionmask]
    # import pdb; pdb.set_trace()
    # define an 8-connected neighborhood
    neighborhood = generate_binary_structure(2, 2)

    # apply the local maximum filter; all pixel of maximal value
    # in their neighborhood are set to 1
    local_max = maximum_filter(image, footprint=neighborhood) == image
    # local_max is a mask that contains the peaks we are
    # looking for, but also the background.
    # In order to isolate the peaks we must remove the background from the mask.

    # we create the mask of the background
    background = image == 0

    # a little technicality: we must erode the background in order to
    # successfully subtract it form local_max, otherwise a line will
    # appear along the background border (artifact of the local maximum filter)
    eroded_background = binary_erosion(background, structure=neighborhood, border_value=1)

    # we obtain the final mask, containing only peaks,
    # by removing the background from the local_max mask (xor operation)
    detected_peaks = local_max ^ eroded_background

    return detected_peaks[regionmask].sum()
