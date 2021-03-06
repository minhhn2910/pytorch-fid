#!/usr/bin/env python3
"""Calculates the Frechet Inception Distance (FID) to evalulate GANs

The FID metric calculates the distance between two distributions of images.
Typically, we have summary statistics (mean & covariance matrix) of one
of these distributions, while the 2nd distribution is given by a GAN.

When run as a stand-alone program, it compares the distribution of
images that are stored as PNG/JPEG at a specified location with a
distribution given by summary statistics (in pickle format).

The FID is calculated by assuming that X_1 and X_2 are the activations of
the pool_3 layer of the inception net for generated samples and real world
samples respectively.

See --help to see further details.

Code apapted from https://github.com/bioinf-jku/TTUR to use PyTorch instead
of Tensorflow

Copyright 2018 Institute of Bioinformatics, JKU Linz

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
import os
import pathlib
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter

import numpy as np
import torch
from scipy import linalg
from torch.nn.functional import adaptive_avg_pool2d
from torchvision import datasets
from PIL import Image

try:
    from tqdm import tqdm
except ImportError:
    # If not tqdm is not available, provide a mock version of it
    def tqdm(x): return x

from inception import InceptionV3

parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
parser.add_argument('path', type=str, nargs=1,
                    help=('Path to the generated images or '
                          'to .npz statistic files'))
parser.add_argument('--batch-size', type=int, default=50,
                    help='Batch size to use')
parser.add_argument('--dims', type=int, default=2048,
                    choices=list(InceptionV3.BLOCK_INDEX_BY_DIM),
                    help=('Dimensionality of Inception features to use. '
                          'By default, uses pool3 features'))
parser.add_argument('-c', '--gpu', default='', type=str,
                    help='GPU to use (leave blank for CPU only)')

parser.add_argument('--rand_data',
                  help='This is a boolean flag.',
                  type=eval, 
                  choices=[True, False], 
                  default='False')

def imread(filename):
    """
    Loads an image file into a (height, width, 3) uint8 ndarray.
    """
    return np.asarray(Image.open(filename), dtype=np.uint8)[..., :3]




def get_activations_numpy(np_array, model, batch_size=256, dims=2048,
                    cuda=False, verbose=False):
    """Calculates the activations of the pool_3 layer for np array.
    -- do normalization + reshape outside of this func
    Params:
    -- files       : List of image files paths
    -- model       : Instance of inception model
    -- batch_size  : Batch size of images for the model to process at once.
                     Make sure that the number of samples is a multiple of
                     the batch size, otherwise some samples are ignored. This
                     behavior is retained to match the original FID score
                     implementation.
    -- dims        : Dimensionality of features returned by Inception
    -- cuda        : If set to True, use GPU
    -- verbose     : If set to True and parameter out_step is given, the number
                     of calculated batches is reported.
    Returns:
    -- A numpy array of dimension (num images, dims) that contains the
       activations of the given tensor when feeding inception with the
       query tensor.
    """
    model.eval()
    print (np_array.shape)
    print ('len ' + str(len(np_array)))
    if batch_size > len(np_array):
        print(('Warning: batch size is bigger than the data size. '
               'Setting batch size to data size'))
        batch_size = len(np_array)

    pred_arr = np.empty((len(np_array), dims))

    for i in tqdm(range(0, len(np_array), batch_size)):
        if verbose:
            print('\rPropagating batch %d/%d' % (i + 1, n_batches),
                  end='', flush=True)
        start = i
        end = i + batch_size

        images = np_array[start:end]#np.array([imread(str(f)).astype(np.float32)
                 #          for f in files[start:end]])

        ## Reshape to (n_images, 3, height, width)
        #(n_images, 3, height, width)
        #images = images.transpose((0, 3, 1, 2)) # no reshape
        #images /= 255 # no normalization

        batch = torch.from_numpy(images).type(torch.FloatTensor)
        if cuda:
            batch = batch.cuda()

        pred = model(batch)[0]

        # If model output is not scalar, apply global spatial average pooling.
        # This happens if you choose a dimensionality not equal 2048.
        if pred.size(2) != 1 or pred.size(3) != 1:
            pred = adaptive_avg_pool2d(pred, output_size=(1, 1))

        pred_arr[start:end] = pred.cpu().data.numpy().reshape(pred.size(0), -1)

    if verbose:
        print(' done')

    return pred_arr

def calculate_frechet_distance(mu1, sigma1, mu2, sigma2, eps=1e-6):
    """Numpy implementation of the Frechet Distance.
    The Frechet distance between two multivariate Gaussians X_1 ~ N(mu_1, C_1)
    and X_2 ~ N(mu_2, C_2) is
            d^2 = ||mu_1 - mu_2||^2 + Tr(C_1 + C_2 - 2*sqrt(C_1*C_2)).

    Stable version by Dougal J. Sutherland.

    Params:
    -- mu1   : Numpy array containing the activations of a layer of the
               inception net (like returned by the function 'get_predictions')
               for generated samples.
    -- mu2   : The sample mean over activations, precalculated on an
               representative data set.
    -- sigma1: The covariance matrix over activations for generated samples.
    -- sigma2: The covariance matrix over activations, precalculated on an
               representative data set.

    Returns:
    --   : The Frechet Distance.
    """

    mu1 = np.atleast_1d(mu1)
    mu2 = np.atleast_1d(mu2)

    sigma1 = np.atleast_2d(sigma1)
    sigma2 = np.atleast_2d(sigma2)

    assert mu1.shape == mu2.shape, \
        'Training and test mean vectors have different lengths'
    assert sigma1.shape == sigma2.shape, \
        'Training and test covariances have different dimensions'

    diff = mu1 - mu2

    # Product might be almost singular
    covmean, _ = linalg.sqrtm(sigma1.dot(sigma2), disp=False)
    if not np.isfinite(covmean).all():
        msg = ('fid calculation produces singular product; '
               'adding %s to diagonal of cov estimates') % eps
        print(msg)
        offset = np.eye(sigma1.shape[0]) * eps
        covmean = linalg.sqrtm((sigma1 + offset).dot(sigma2 + offset))

    # Numerical error might give slight imaginary component
    if np.iscomplexobj(covmean):
        if not np.allclose(np.diagonal(covmean).imag, 0, atol=1e-3):
            m = np.max(np.abs(covmean.imag))
            raise ValueError('Imaginary component {}'.format(m))
        covmean = covmean.real

    tr_covmean = np.trace(covmean)

    return (diff.dot(diff) + np.trace(sigma1) +
            np.trace(sigma2) - 2 * tr_covmean)



def calculate_fid_mnist_npy(path, batch_size, cuda, dims, rand_data):
    """Calculates the FID of two paths"""
    block_idx = InceptionV3.BLOCK_INDEX_BY_DIM[dims]

    model = InceptionV3([block_idx])
    if cuda:
        model.cuda()
    m1 = np.array([])
    s1 = np.array([])
    if (os.path.exists('./fid_stats_lsun_train.npz')):
        f = np.load('./fid_stats_lsun_train.npz')
        m1, s1 = f['mu'][:], f['sigma'][:]
        f.close()
    else:
        print('could not find precomputed lsun stats, exiting')
        exit(0)

    
    
    np_1 = np.load(path[0])
    np_1 = np_1*0.5 + 0.5
    #np_1 = np.repeat(np_1, 3, axis=1) 
    print ("min %f  max %f " %( min(np_1.flatten()), max(np_1.flatten())))
    act2 = get_activations_numpy(np_1, model, batch_size, dims, cuda)
    m2 = np.mean(act2, axis=0)
    s2 = np.cov(act2, rowvar=False)
    
    fid_value = calculate_frechet_distance(m1, s1, m2, s2)
    
    print('FID: ', fid_value)
    if (rand_data):
        np.random.seed()
        rand_data = np.random.rand(*np_1.shape) #*before a tuple shape to unpack its content
        act2 = get_activations_numpy(rand_data, model, batch_size, dims, cuda)
        m2 = np.mean(act2, axis=0)
        s2 = np.cov(act2, rowvar=False)

        fid_value = calculate_frechet_distance(m1, s1, m2, s2)

        print('FID rand data: ', fid_value)

    #return fid_value

def calculate_fid_mnist_test_set(path, batch_size, cuda, dims):
    """Calculates the FID of two paths"""
    block_idx = InceptionV3.BLOCK_INDEX_BY_DIM[dims]

    model = InceptionV3([block_idx])
    if cuda:
        model.cuda()
        
    test_set = datasets.MNIST('/tmp/mnist-data', train=False, download=True)
    test_set = test_set.data.numpy()
    test_set = test_set.reshape(10000,1,28,28)
    test_set = test_set/255.0
    test_set = np.repeat(test_set, 3, axis=1)
    act1 = get_activations_numpy(test_set, model, batch_size, dims, cuda)
    m1 = np.mean(act1, axis=0)
    s1 = np.cov(act1, rowvar=False)
    np.save('./mnist-mean.npy', m1)
    np.save('./mnist-cov.npy', s1)
    
    
if __name__ == '__main__':
    args = parser.parse_args()
    os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu
#     calculate_fid_mnist_test_set (args.path,
#                                           args.batch_size,
#                                           args.gpu != '',
#                                           args.dims)
                                  
    calculate_fid_mnist_npy(args.path,
                                         args.batch_size,
                                         args.gpu != '',
                                         args.dims,
                                         args.rand_data
                                       )

    #print('FID: ', fid_value)
