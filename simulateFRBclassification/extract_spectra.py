#!/usr/bin/python

import numpy as np
import argparse
import glob

# paths needed to use filterbank and waterfaller modules
import sys
sys.path.append('/usr/local/lib/python2.7/dist-packages/')
sys.path.append('/home/vgajjar/linux64_bin/lib/python2.7/site-packages/')

# generate Spectra objects for FRB injection
from waterfaller import filterbank, waterfall

"""Converts filterbank files to Spectra objects, which will then be used to
artifically inject FRBs and train a neural network on. Takes in as input
a directory of pertinent filterbank files."""

def fil2spec(fname, num_channels, spectra_array):
    # get filterbank file as input and output a Spectra object
    raw_filterbank_file = filterbank.FilterbankFile(fname)

    # loop over entire filterbank file in 256 bin multiples until reaching the end
    finished_scanning = False

    while not finished_scanning:
        timestep = 0
        try:
            # get spectra object at some timestep, incrementing timestep if successful
            spectra_obj = waterfall(raw_filterbank_file, start=timestep, duration=raw_filterbank_file.dt,
                                    dm=0, nbins=256, nsub=num_channels)
            spectra_array.append(spectra_obj)
            timestep += 1
            print('Finished scan number ' + str(timestep))
        except AssertionError as error:
            # empty AssertionError is the correct case to break loop and stop scanning
            if not str(error):
                finished_scanning = True
                print('Finished scanning "{0}"'.format(raw_filterbank_file.filename))
            else:
                raise ValueError('An unknown error was caught when scanning over filterbank file!')

    freq = raw_filterbank_file.frequencies

    return spectra_array, freq

def chop_off(array):
    """
    Splits long 2D array into 3D array of multiple 2D arrays,
    such that each has 256 time bins. Drops the last chunk if it
    has fewer than 256 bins.
    """

    # split array into multiples of 256
    subsections = np.arange(256, array.shape[-1], 256)
    print('Splitting each array into {0} blocks'.format(len(subsections) + 1))
    split_array = np.split(array, subsections, axis=2)

    if split_array[-1].shape[-1] < 256:
        split_array.pop()

    combined_chunks = np.concatenate(split_array, axis=0)
    print('Array shape after splitting: {0}'.format(combined_chunks.shape))

    return combined_chunks

def remove_extras(array, num_samples):
    """
    Randomly removes a certain number of Spectra objects such that
    there are num_samples Spectra in the output.
    """
    assert num_samples <= len(array), "More samples needed than array has"
    leftovers = np.random.choice(array, size=num_samples, replace=False)

    print('Removing {0} random arrays'.format(len(array) - num_samples))
    return leftovers


if __name__ == "__main__":
    # Read command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('path_RFI', type=str)
    parser.add_argument('--num_samples', type=int, default=320, help='Number of RFI arrays to generate')
    parser.add_argument('--save_name', type=str, default='psr_arrays.npz',
                        help='Filename to save frequency-time arrays')

    parser.add_argument('--NCHAN', type=int, default=64,
                        help='Number of frequency channels to resize psrchive files to')

    parser.add_argument('--min_DM', type=float, default=0.0, help='Minimum DM to sample')
    parser.add_argument('--max_DM', type=float, default=1000.0, help='Maximum DM to sample')

    args = parser.parse_args()

    path = args.path_RFI
    save_name = args.save_name
    NCHAN = args.NCHAN

    files = glob.glob(path + "*.fil" if path[-1] == '/' else path + '/*.fil')
    print("\nNumber of files to sample from: %d" % len(files))

    if not files:
        raise ValueError("No files found in path " + path)

    # choose DM randomly from a uniform distribution
    random_files = []
    random_DMs = np.random.uniform(low=args.min_DM, high=args.max_DM, size=args.num_samples)

    # extract spectra from .fil files until number of samples is reached
    spectra_samples = []

    while len(spectra_samples) < args.num_samples:
        # pick a random filterbank file from directory
        rand_filename = np.random.choice(files)
        random_files.append(rand_filename)
        print("Sampling file: " + str(rand_filename))

        # get spectra information and append to growing list of samples
        spectra_samples, freq = fil2spec(rand_filename, NCHAN, spectra_samples)
        print("Finished! Number of samples after scan: " + str(len(spectra_samples)))

    print("Unique number of files after random sampling: " + str(len(np.unique(random_files))))

    # remove extra samples, since last file may have provided more than needed
    spectra_samples = remove_extras(spectra_samples, args.num_samples)

    # save final array to disk
    print("Saving arrays to {0}".format(save_name))
    np.savez(save_name, spectra_data=spectra_samples, freq=freq)
