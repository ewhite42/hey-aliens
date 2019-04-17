# /usr/local/python3

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys, os
import numpy as np
from scipy.signal import gaussian, fftconvolve
import time
import h5py
import random
from tqdm import tqdm  # progress bar
import argparse  # to parse arguments in command line
import tensorflow as tf
import glob

"""Adapted from the code published from the paper 'Applying Deep Learning 
to Fast Radio Burst Classification' by Liam Connor and Joeri van Leeuwen, as
well as code wrapping done by Vishal Gajjar."""

"""Trains a convolutional neural network to recognize differences between fast
radio bursts and RFI. Training is done by simulating a specified number of FRB
examples and injecting them into noisy backgrounds."""

try:
    import matplotlib
    import matplotlib.pyplot as plt
    from matplotlib import gridspec

    print("Worked")
except:
    "Didn't work"
    pass

# import psrchive as psr

tf.logging.set_verbosity(tf.logging.INFO)

import keras
from keras.models import Sequential
from keras.layers import Dense, Dropout, Flatten
from keras.layers import merge as Merger
from keras.layers import Conv1D, Conv2D
from keras.layers import MaxPooling2D, MaxPooling1D, GlobalAveragePooling1D, BatchNormalization
from keras.optimizers import SGD, Adam
from keras.models import load_model


def construct_conv2d(model_name, features_only=False, fit=False,
                     train_data=None, train_labels=None,
                     eval_data=None, eval_labels=None,
                     nfreq=16, ntime=250, epochs=5,
                     nfilt1=32, nfilt2=64, batch_size=32):
    """ Build a two-dimensional convolutional neural network
    with a binary classifier. Can be used for, e.g.,
    freq-time dynamic spectra of pulsars, dm-time intensity array.

    Parameters:
    ----------
    features_only : bool 
        Don't construct full model, only features layers 
    fit : bool 
        Fit model 
    train_data : ndarray
        (ntrain, ntime, 1) float64 array with training data
    train_labels :  ndarray
        (ntrigger, 2) binary labels of training data [0, 1] = FRB, [1, 0]=RFI 
    eval_data : ndarray
        (neval, ntime, 1) float64 array with evaluation data
    eval_labels : 
        (neval, 2) binary labels of eval data 
    epochs : int 
        Number of training epochs 
    nfilt1 : int
        Number of neurons in first hidden layer 
    nfilt2 : int 
        Number of neurons in second hidden layer 
    batch_size : int 
        Number of batches for training   
       
    Returns
    -------
    model : XX

    score : np.float 
        accuracy, i.e. fraction of predictions that are correct 

    """

    if train_data is not None:
        nfreq = train_data.shape[1]
        ntime = train_data.shape[2]

    print(nfreq, ntime)
    model = Sequential()
    # this applies 32 convolution filters of size 5x5 each.
    model.add(Conv2D(nfilt1, (5, 5), activation='relu', input_shape=(nfreq, ntime, 1)))

    model.add(MaxPooling2D(pool_size=(2, 2)))

    # Randomly drop some fraction of nodes (set weights to 0)
    model.add(Dropout(0.4))
    model.add(Conv2D(nfilt2, (5, 5), activation='relu'))
    model.add(MaxPooling2D(pool_size=(2, 2)))
    model.add(Dropout(0.4))
    model.add(Flatten())

    if features_only is True:
        model.add(BatchNormalization())  # hack
        return model, []

    model.add(Dense(256, activation='relu'))  # should be 1024 hack

    #    model.add(Dense(1024, activation='relu')) # remove for now hack
    model.add(Dropout(0.5))
    model.add(Dense(2, activation='softmax'))

    sgd = SGD(lr=0.01, decay=1e-6, momentum=0.9, nesterov=True)
    model.compile(loss='binary_crossentropy', optimizer=sgd, metrics=['accuracy'])

    # train_labels = keras.utils.to_categorical(train_labels)
    # eval_labels = keras.utils.to_categorical(eval_labels)

    if fit is True:
        print("Using batch_size: %d" % batch_size)
        print("Using %d epochs" % epochs)
        cb = keras.callbacks.TensorBoard(log_dir='./logs', histogram_freq=0,
                                         batch_size=32, write_graph=True, write_grads=False,
                                         write_images=True, embeddings_freq=0, embeddings_layer_names=None,
                                         embeddings_metadata=None)

        # save best model
        best_model_cb = keras.callbacks.ModelCheckpoint(f"{model_name}", monitor='val_acc', verbose=1,
                                                        save_best_only=True)
        model.fit(train_data, train_labels, validation_data=(eval_data, eval_labels),
                  batch_size=batch_size, epochs=epochs, callbacks=[cb, best_model_cb])

        score = model.evaluate(eval_data, eval_labels, batch_size=batch_size)
        print("Conv2d only")
        print(score)

    return model, score


def get_classification_results(y_true, y_pred, test_SNR=None):
    """ Take true labels (y_true) and model-predicted 
    label (y_pred) for a binary classifier, and return 
    true_positives, false_positives, true_negatives, false_negatives
    """
    if test_SNR is not None:
        TP_ind = np.argwhere((y_true == 1) & (y_pred == 1))
        FP_ind = np.argwhere((y_true == 0) & (y_pred == 1))
        TN_ind = np.argwhere((y_true == 0) & (y_pred == 0))
        FN_ind = np.argwhere((y_true == 1) & (y_pred == 0))
        SNR_TP, SNR_FP, SNR_TN, SNR_FN = test_SNR[TP_ind], test_SNR[FP_ind], test_SNR[TN_ind], test_SNR[FN_ind]
        return SNR_TP.flatten(), SNR_FP.flatten(), SNR_TN.flatten(), SNR_FN.flatten()
    else:
        true_positives = np.where((y_true == 1) & (y_pred == 1))[0]
        false_positives = np.where((y_true == 0) & (y_pred == 1))[0]
        true_negatives = np.where((y_true == 0) & (y_pred == 0))[0]
        false_negatives = np.where((y_true == 1) & (y_pred == 0))[0]
        return true_positives, false_positives, true_negatives, false_negatives


def confusion_mat(y_true, y_pred):
    """ Generate a confusion matrix for a
    binary classifier based on true labels (
    y_true) and model-predicted label (y_pred)

    returns np.array([[TP, FP],[FN, TN]])
    """
    TP, FP, TN, FN = get_classification_results(y_true, y_pred)

    NTP = len(TP)
    NFP = len(FP)
    NTN = len(TN)
    NFN = len(FN)

    conf_mat = np.array([[NTP, NFP], [NFN, NTN]])
    return conf_mat


def print_metric(y_true, y_pred):
    """ Take true labels (y_true) and model-predicted 
    label (y_pred) for a binary classifier
    and print a confusion matrix, metrics, 
    return accuracy, precision, recall, fscore
    """
    conf_mat = confusion_mat(y_true, y_pred)

    NTP, NFP, NTN, NFN = conf_mat[0, 0], conf_mat[0, 1], conf_mat[1, 1], conf_mat[1, 0]

    print("Confusion matrix:")

    print('\n'.join([''.join(['{:8}'.format(item) for item in row])
                     for row in conf_mat]))

    accuracy = float(NTP + NTN) / conf_mat.sum()
    precision = float(NTP) / (NTP + NFP + 1e-19)
    recall = float(NTP) / (NTP + NFN + 1e-19)
    fscore = 2 * precision * recall / (precision + recall)

    print("accuracy: %f" % accuracy)
    print("precision: %f" % precision)
    print("recall: %f" % recall)
    print("fscore: %f" % fscore)

    return accuracy, precision, recall, fscore

class SimulatedFRB(object):
    """ Class to generate a realistic fast radio burst and 
    add the event to data, including scintillation and 
    temporal scattering. @source liamconnor
    """
    def __init__(self, shape=(64, 256), f_ref=1350, bandwidth=1500, max_width=4, tau=0.1):
        assert type(shape) == tuple and len(shape) == 2, "shape needs to be a tuple of 2 integers"
        # assert type(tau_range) == tuple and len(tau_range) == 2, "tau_range needs to be a tuple of 2 integers"
        
        self.shape = shape

        # reference frequency (MHz) of observations
        self.f_ref = f_ref
        
        # maximum width of pulse, high point of uniform distribution for pulse width
        self.max_width = max_width 
        
        # number of bins/data points on the time (x) axis
        self.nt = shape[1] 
        
        # frequency range for the pulse, given the number of channels
        self.frequencies = np.linspace(f_ref - bandwidth // 2, f_ref + bandwidth // 2, shape[0])

        # where the pulse will be centered on the time (x) axis
        self.t0 = np.random.randint(-shape[1] + max_width, shape[1] - max_width) 

        # scattering timescale (milliseconds)
        self.tau = tau

        # randomly generated SNR and FRB generated after calling injectFRB()
        self.SNR = None
        self.FRB = None

        '''Simulates background noise similar to the .ar 
        files. Backgrounds will be injected with FRBs to 
        be used in classification later on.'''
        self.background = np.random.randn(*self.shape)

    def gaussian_profile(self):
        """Model pulse as a normalized Gaussian."""
        t = np.linspace(-self.nt // 2, self.nt // 2, self.nt)
        g = np.exp(-(t / np.random.randint(1, self.max_width))**2)
        
        if not np.all(g > 0):
            g += 1e-18

        # clone Gaussian into 2D array with NFREQ rows
        return np.tile(g, (self.shape[0], 1))
    
    def scatter_profile(self):
        """ Include exponential scattering profile."""
        tau_nu = self.tau * (self.frequencies / self.f_ref) ** -4
        t = np.linspace(0, self.nt//2, self.nt)

        prof = np.exp(-t / tau_nu.reshape(-1, 1)) / tau_nu.reshape(-1, 1)
        return prof / np.max(prof, axis=1).reshape(-1, 1)

    def pulse_profile(self):
        """ Convolve the gaussian and scattering profiles
        for final pulse shape at each frequency channel.
        """
        gaus_prof = self.gaussian_profile()
        scat_prof = self.scatter_profile()
        
        # convolve the two profiles for each frequency
        pulse_prof = np.array([fftconvolve(gaus_prof[i], scat_prof[i])[:self.nt] for i in np.arange(self.shape[0])])

        # normalize! high frequencies should have narrower pulses
        pulse_prof /= np.trapz(pulse_prof, axis=1).reshape(-1, 1)
        return pulse_prof

    def scintillate(self):
        """ Include spectral scintillation across the band.
        Approximate effect as a sinusoid, with a random phase
        and a random decorrelation bandwidth.
        """
        # Make location of peaks / troughs random
        scint_phi = np.random.rand()

        # Make number of scintils between 0 and 10 (ish)
        nscint = np.exp(np.random.uniform(np.log(1e-3), np.log(7)))

        if nscint < 1:
            nscint = 0

        envelope = np.cos(2 * np.pi * nscint * (self.frequencies / self.f_ref)**-2 + scint_phi)
        
        # set all negative elements to zero and add small factor
        envelope[envelope < 0] = 0
        envelope += 0.1

        # add scintillation to pulse profile
        pulse = self.pulse_profile()
        pulse *= envelope.reshape(-1, 1)
        self.FRB = pulse
        return pulse

    def roll(self):
        """Move FRB to random location of the time axis (in-place),
        ensuring that the shift does not cause one end of the FRB
        to end up on the other side of the array."""
        if self.FRB is None:
            self.scintillate()

        bin_shift = np.random.randint(low = -self.shape[1] // 2 + self.max_width,
                                      high = self.shape[1] // 2 - self.max_width)
        self.FRB = np.roll(self.FRB, bin_shift, axis=1)

    def injectFRB(self, SNRmin=8, SNR_sigma=1.0, returnSNR=False):
        """Inject an FRB modeling a Gaussian waveform input 2D data array"""
        data = np.array(self.background)
        nchan, nbins = self.shape

        # Fraction of frequency axis for the signal
        frac = np.random.uniform(0.5, 0.9)

        wid = np.random.randint(1, self.max_width)  # Width range of the injected burst in number of bins

        st = random.randint(0, nbins - wid)  # Random point to inject FRB

        prof = np.mean(data, axis=0)

        # sample peak SNR from log-normal distribution to create Gaussian signal
        randomSNR = SNRmin + np.random.lognormal(mean=1.0, sigma=SNR_sigma)
        peak_value = randomSNR * np.std(prof)

        # make a signal that follows scattering profile given above
        signal = peak_value * self.pulse_profile()

        # Partial inject
        stch = np.random.randint(0, nchan - (nchan) * frac)
        data[stch:int(stch + (nchan * frac)), st:st + wid] = data[stch:int(stch + (nchan * frac)), st:st + wid] + signal

        if returnSNR:
            return data, randomSNR
        return data


def psr2np(fname, NCHAN, dm):
    # Get psrchive file as input and outputs numpy array
    fpsr = psr.Archive_load(fname)
    fpsr.dededisperse()
    fpsr.set_dispersion_measure(dm)
    fpsr.dedisperse()

    fpsr.fscrunch_to_nchan(NCHAN)
    fpsr.remove_baseline()

    # -- apply weights for RFI lines --#
    ds = fpsr.get_data().squeeze()
    w = fpsr.get_weights().flatten()
    w = w / np.max(w)
    idx = np.where(w == 0)[0]
    ds = np.multiply(ds, w[np.newaxis, :, np.newaxis])
    ds[:, idx, :] = np.nan

    # -- Get total intensity data (I) from the full stokes --#
    data = ds[0, :, :]

    # -- Get frequency axis values --#
    freq = np.linspace(fpsr.get_centre_frequency() - abs(fpsr.get_bandwidth() / 2),
                       fpsr.get_centre_frequency() + abs(fpsr.get_bandwidth() / 2), fpsr.get_nchan())

    # -- Get time axis --#
    tbin = float(fpsr.integration_length() / fpsr.get_nbin())
    taxis = np.arange(0, fpsr.integration_length(), tbin)
    # Convert to time to msec
    taxis = taxis * 1000

    return data


def make_labels(num_data, SNRmin):
    '''Simulates the background for num_data number of points and appends to ftdata.
    Each iteration will have just noise and an injected FRB, so the label list should
    be populated with just 0 and 1, which will then be shuffled later.'''

    ftdata = []
    labels = []
    SNR_values = []

    for sim in np.arange(num_data):
        # previously, ar file with FRB
        # now, filled with simulated data
        fake_noise = simulate_background()

        # put simulated data into ftdata and label it RFI
        ftdata.append(fake_noise)
        labels.append(0)

        # inject FRB into data and label it true
        frb_array, SNR = gaussianFRB(data=fake_noise, SNRmin=SNRmin, returnSNR=True)
        ftdata.append(frb_array)
        labels.append(1)
        SNR_values.extend([SNR, SNR])

    return np.array(ftdata), np.array(labels), np.array(SNR_values)


if __name__ == "__main__":
    # Read command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--num_samples', metavar='num_samples', type=int, default=1000,
                        help='Number of samples to train neural network on')
    parser.add_argument('--snr', type=float, default=10.0, 
                        help='Minimum SNR for FRB signal')
    parser.add_argument('--epochs', type=int, default=32,
                        help='Number of epochs to train with')
    parser.add_argument('--save', dest='best_model_file', type=str, default='best_model.h5',
                        help='Filename to save best model in')
    parser.add_argument('--confmatname', metavar='confusion matrix name', type=str,
                        default='confusion matrix.png',
                        help='Filename to store final confusion matrix in')

    args = parser.parse_args()

    # Read archive files and extract data arrays
    best_model_name = args.best_model_file  # Path and Pattern to find all the .ar files to read and train on
    SNRmin = args.snr
    confusion_matrix_name = args.confmatname

    NFREQ = 64
    NTINT = 256
    DM = 102.4

    '''if path is not None:
        #files = glob.glob(path+"1stCand*.ar")
        files = glob.glob(path+"*.ar")
    else:    
        #files = glob.glob("1stCand*.ar")
        files = glob.glob("*.ar")
   
    ftdata = [] 
    label = []

    for fl in files:
        
        cmd = "pdv -t " + fl + " | awk '{print$4}' >  test.text"
        print(cmd)
        os.system(cmd)
        data = np.loadtxt("test.text",skiprows=1) 
        data = np.reshape(data,(NFREQ,NTINT)) 
        ftdata.append(data)
        
        #ar file with FRB
        data = []
        #data = psr2np(fl,NFREQ,30)
        ftdata.append(psr2np(fl,NFREQ,DM))
        label.append(0)
        #ar file with injected FRB
        data1 = []
        data1 = injectFRB(psr2np(fl,NFREQ,30))
        ftdata.append(data1)
        label.append(1)

    ftdata = np.array(ftdata)'''

    # n_sims passed into the interpreter
    ftdata, label, SNRs = make_labels(args.num_samples, SNRmin)

    if ftdata is not None:
        Nfl = ftdata.shape[0]
        nfreq = ftdata.shape[1]
        ntime = ftdata.shape[2]

    print(Nfl, nfreq, ntime)
    print(label)

    dshape = ftdata.shape

    # normalize data
    ftdata = ftdata.reshape(len(ftdata), -1)
    ftdata -= np.median(ftdata, axis=-1)[:, None]
    ftdata /= np.std(ftdata, axis=-1)[:, None]

    # zero out nans
    ftdata[ftdata != ftdata] = 0.0
    ftdata = ftdata.reshape(dshape)

    # Get 4D vector for Keras
    ftdata = ftdata[..., None]

    NTRAIN = int(len(label) * 0.5)

    ind = np.arange(Nfl)
    np.random.shuffle(ind)

    # split indices into training and evaluation set
    ind_train = ind[:NTRAIN]
    ind_eval = ind[NTRAIN:]

    train_data_freq, eval_data_freq = ftdata[ind_train], ftdata[ind_eval]

    train_labels, eval_labels = label[ind_train], label[ind_eval]
    # avoids using the keras labels I guess?
    eval_label1 = np.array(eval_labels)

    train_labels = keras.utils.to_categorical(train_labels)
    eval_labels = keras.utils.to_categorical(eval_labels)

    os.environ['HDF5_USE_FILE_LOCKING'] = 'FALSE'
    # Fit convolution neural network to the training data
    model_freq_time, score_freq_time = construct_conv2d(best_model_name,
                                                        features_only=False, fit=True,
                                                        train_data=train_data_freq, eval_data=eval_data_freq,
                                                        train_labels=train_labels, eval_labels=eval_labels,
                                                        epochs=args.epochs, nfilt1=32, nfilt2=64,
                                                        nfreq=NFREQ, ntime=NTINT)

    y_pred_prob1 = model_freq_time.predict(eval_data_freq)
    y_pred_prob = y_pred_prob1[:, 1]
    y_pred_freq_time = np.array(list(np.round(y_pred_prob)))
    metrics = print_metric(eval_label1, y_pred_freq_time)

    TP, FP, TN, FN = get_classification_results(eval_label1, y_pred_freq_time)

    # Get SNRs for images in each of the confusion matrix areas
    eval_SNR = SNRs[ind_eval]
    SNR_TP, SNR_FP, SNR_TN, SNR_FN = get_classification_results(eval_label1, y_pred_freq_time, test_SNR=eval_SNR)

    if TP.size:
        TPind = TP[np.argmin(y_pred_prob[TP])]  # Min probability True positive candidate
        TPdata = eval_data_freq[..., 0][TPind]
    else:
        TPdata = np.zeros((NFREQ, NTINT))

    if FP.size:
        FPind = FP[np.argmax(y_pred_prob[FP])]  # Max probability False positive candidate
        FPdata = eval_data_freq[..., 0][FPind]
    else:
        FPdata = np.zeros((NFREQ, NTINT))

    if FN.size:
        FNind = FN[np.argmax(y_pred_prob[FN])]  # Max probability False negative candidate
        FNdata = eval_data_freq[..., 0][FNind]
    else:
        FNdata = np.zeros((NFREQ, NTINT))

    if TN.size:
        TNind = TN[np.argmin(y_pred_prob[TN])]  # Min probability True negative candidate
        TNdata = eval_data_freq[..., 0][TNind]
    else:
        TNdata = np.zeros((NFREQ, NTINT))

    plt.subplot(221)
    plt.gca().set_title('TP')
    plt.imshow(TPdata, aspect='auto', interpolation='none')
    plt.subplot(222)
    plt.gca().set_title('FP')
    plt.imshow(FPdata, aspect='auto', interpolation='none')
    plt.subplot(223)
    plt.gca().set_title('FN')
    plt.imshow(FNdata, aspect='auto', interpolation='none')
    plt.subplot(224)
    plt.gca().set_title('TN')
    plt.imshow(TNdata, aspect='auto', interpolation='none')

    plt.savefig(confusion_matrix_name)

    plt.show()