from abc import ABCMeta, abstractproperty

from astropy import units as u
import numpy as np
from astropy.io import fits

from . import wcs_manipulation

__all__ = ['SpectralCube']


class MaskBase(object):
    __metaclass__ = ABCMeta

    @abstractproperty
    def include(self):
        pass

    def _flat(self, cube):
        """
        Return a flattened array of the included elements of cube

        Parameters
        ----------
        cube : array-like
           The cube to extract

        Returns
        -------
        A 1D ndarray

        Notes
        -----
        This is an internal method used by :class:`SpectralCube`.
        """
        return cube[self.include]

    def _filled(self, array, fill=np.nan):
        """
        Replace the exluded elements of *array* with *fill*.

        Parameters
        ----------
        array : array-like
            Input array
        fill : number
            Replacement value

        Returns
        -------
        A new array

        Notes
        -----
        This is an internal method used by :class:`SpectralCube`.
        Users should use :meth:`SpectralCubeMask.get_data`
        """
        return np.where(self.include, array, fill)

    @property
    def exclude(self):
        return np.logical_not(self.include)


class SpectralCubeMask(MaskBase):

    def __init__(self, mask, wcs, include=True):
        self._wcs = wcs
        self._includemask = mask if include else np.logical_not(mask)

    @property
    def include(self):
        return self._includemask

    def __getitem__(self, slice):
        # TODO: need to update WCS!
        return SpectralCube(self._includemask[slice], self._wcs)


class SpectralCube(object):

    def __init__(self, data, wcs, mask=None, metadata=None):
        self._data, self._wcs = _orient(data, wcs)
        self._spectral_axis = None
        self._mask = mask  # specifies which elements to Nan/blank/ignore -> SpectralCubeMask
                           # object or array-like object, given that WCS needs to be consistent with data?
        #assert mask._wcs == self._wcs
        self.metadata = metadata or {}

    def _oriented_wcs(self):
        raise NotImplementedError()

        for ii, ax in enumerate(axtypes):
            if ax['coordinate_type'] == 'spectral':
                specaxisnumber = ii

        if specaxisnumber != 0:
            self._data = self._data.swapaxes(specaxisnumber, 0)
            self._wcs = wcs_manipulation.wcs_swapaxes(self._wcs, specaxisnumber, 0)

    @property
    def shape(self):
        return self._data.shape

    @classmethod
    def read(cls, filename, format=None):
        if format == 'fits':
            from .io.fits import load_fits_cube
            return load_fits_cube(filename)
        elif format == 'casa_image':
            from .io.casa_image import load_casa_image
            return load_casa_image(filename)
        else:
            raise ValueError("Format {0} not implemented".format(format))

    def write(self, filename, format=None, includestokes=False, clobber=False):
        if format == 'fits':
            data = self._data
            wcs = self._wcs
            axtypes = wcs.get_axis_types()
            stokesax = np.array([a['coordinate_type'] == 'stokes' for a in axtypes])
            if not includestokes:
                if data.shape[0] != 1:
                    raise ValueError("Cannot drop stokes unless it's degenerate")
                data = data[0,:,:,:]
                if np.any(stokesax):
                    drop = np.argmax(stokesax)
                    wcs = wcs_manipulation.drop_axis(wcs, drop)
            else:
                if not np.any(stokesax):
                    wcs = wcs_manipulation.add_stokes_axis_to_wcs(wcs, 0)

            header = wcs.to_header()
            outhdu = fits.PrimaryHDU(data=data, header=header)
            outhdu.writeto(filename, clobber=clobber)
        else:
            raise NotImplementedError("Try FITS instead")

    def sum(self, axis=None):
        pass

    def max(self, axis=None):
        pass

    def min(self, axis=None):
        pass

    def argmax(self, axis=None):
        pass

    def argmin(self, axis=None):
        pass

    def interpolate_slice(self):
        # Find a slice at an exact spectral value?
        pass

    @property
    def data_valid(self):
        """ Flat array of unmasked data values """
        return self._data[self.mask.include]

    def chunked(self, chunksize=1000):
        """
        Iterate over chunks of valid data
        """
        raise NotImplementedError()

    def get_data(self, fill=np.nan):
        """
        Return the underlying data as a numpy array.
        Always returns the spectral axis as the 0th axis

        Sets masked values to *fill*
        """
        if self._mask is None:
            return self._data[0]

        return self._mask._filled(self._data[0], fill)

    @property
    def data_unmasked(self):
        """
        Like data, but don't apply the mask
        """

    def apply_mask(self, mask, inherit=True):
        """
        Return a new Cube object, that applies the input mask to the underlying data.

        Handles any necessary logic to resample the mask

        If inherit=True, the new Cube uses the union of the original and new mask

        What type of object is `mask`? SpectralMask?
        Not sure -- I guess it needs to have WCS. Conceptually maps onto a boolean ndarray
            CubeMask? -> maybe SpectralCubeMask to be consistent with SpectralCube

        """

    def moment(self, order, wcs=False):
        """
        Determine the n'th moment along the spectral axis

        If *wcs = True*, return the WCS describing the moment
        """

    @property
    def spectral_axis(self):
        """
        A `~astropy.units.Quantity` array containing the central values of
        each channel along the spectral axis.
        """

        # TODO: use world[...] once implemented
        iz, iy, ix = np.broadcast_arrays(np.arange(self.shape[0]), 0., 0.)
        return self._wcs.all_pix2world(ix, iy, iz, 0)[2] * u.Unit(self._wcs.wcs.cunit[2])

    def closest_spectral_channel(self, value, rest_frequency=None):
        """
        Find the index of the closest spectral channel to the specified
        spectral coordinate.

        Parameters
        ----------
        value : :class:`~astropy.units.Quantity`
            The value of the spectral coordinate to search for.
        rest_frequency : :class:`~astropy.units.Quantity`
            The rest frequency for any Doppler conversions
        """

        # TODO: we have to not compute this every time
        spectral_axis = self.spectral_axis

        try:
            value = value.to(spectral_axis.unit, equivalencies=u.spectral())
        except u.UnitsError:
            if rest_frequency is None:
                raise u.UnitsError("{0} cannot be converted to {1} without a "
                                   "rest frequency".format(value.unit, spectral_axis.unit))
            else:
                try:
                    value = value.to(spectral_axis.unit,
                                     equivalencies=u.doppler_radio(rest_frequency))
                except u.UnitsError:
                    raise u.UnitsError("{0} cannot be converted to {1}".format(value.unit, spectral_axis.unit))

        # TODO: optimize the next line - just brute force for now
        return np.argmin(np.abs(spectral_axis - value))

    def spectral_slab(self, lo, hi, rest_frequency=None):
        """
        Extract a new cube between two spectral coordinates

        Parameters
        ----------
        lo, hi : :class:`~astropy.units.Quantity`
            The lower and upper spectral coordinate for the slab range
        rest_frequency : :class:`~astropy.units.Quantity`
            The rest frequency for any Doppler conversions
        """

        # Find range of values for spectral axis
        ilo = self.closest_spectral_channel(lo, rest_frequency=rest_frequency)
        ihi = self.closest_spectral_channel(hi, rest_frequency=rest_frequency)

        if ilo > ihi:
            ilo, ihi = ihi, ilo
        elif ilo == ihi:
            ihi += 1

        # Create WCS slab
        wcs_slab = self._wcs.copy()
        wcs_slab.wcs.crpix[1] -= ilo

        # Create mask slab
        if self._mask is None:
            mask_slab = None
        else:
            mask_slab = self._mask[:,ilo:ihi]

        # Create new spectral cube
        slab = SpectralCube(self._data[:,ilo:ihi], wcs_slab,
                            mask=mask_slab, metadata=self.metadata)

        return slab

    def world_spines(self):
        """
        Returns a dict of 1D arrays, for the world coordinates
        along each pixel axis.

        Raises error if this operation is ill-posed (e.g. rotated world coordinates,
        strong distortions)
        """

    @property
    def world(self):
        """
        Access the world coordinates for the cube, as if it was a Numpy array, so:

        >>> cube.world[0,:,:]

        returns a dictionary of 2-d arrays giving the coordinates in the first spectral slice.

        This can be made to only compute the required values rather than compute everything then slice.
        """


def _orient(data, wcs):
    if data.ndim not in [3, 4]:
        raise ValueError("Input array must be 3 or 4 dimensional")

    axtypes = wcs.get_axis_types()[::-1]  # reverse from wcs -> numpy convention
    types = [a['coordinate_type'] for a in axtypes]
    nums = [None if a['coordinate_type'] != 'celestial' else a['number']
            for a in axtypes]

    if 'stokes' in types:
        t = [types.index('stokes'),
             types.index('spectral'),
             nums.index(1), nums.index(0)]
        result = data.transpose(t)
    else:
        t = [types.index('spectral'),
             nums.index(1), nums.index(0)]
        result = data.transpose(t)[np.newaxis]

    return result, wcs


# demo code


def test():
    x = SpectralCube()
    x2 = SpectralCube()
    x.sum(axis='spectral')
    # optionally:
    x.sum(axis=0)  # where 0 is defined to be spectral
    x.moment(3)  # kurtosis?  moment assumes spectral
    (x * x2).sum(axis='spatial1')