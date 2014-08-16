#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import (division, print_function, absolute_import,
                        unicode_literals)

__all__ = ["main"]

import os
import h5py
import fitsio
import turnstile
import numpy as np
from scipy.stats import beta
from multiprocessing import Pool
from itertools import izip, ifilter


def setup_pipeline(cache=False):
    pipe = turnstile.Download(cache=cache)
    pipe = turnstile.Inject(pipe, cache=False)
    pipe = turnstile.Prepare(pipe, cache=False)
    pipe = turnstile.Detrend(pipe, cache=cache)
    return pipe


def load_stars():
    fn = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "42k.fits.gz")
    return fitsio.read(fn)


def generate_system(K, mstar=1.0, rstar=1.0):
    labels = ["period", "t0", "radius", "b", "e", "pomega", "q1", "q2"]

    periods = np.exp(np.random.uniform(np.log(50), np.log(450), K))
    t0s = np.array([np.random.uniform(0, p) for p in periods])
    radii = np.random.uniform(0.01, 0.04, K)
    b = np.random.uniform(0, 1, K)
    e = beta.rvs(0.867, 3.03, size=K)
    pomega = np.random.uniform(0, 2*np.pi, K)
    q1 = np.random.uniform(0, 1)
    q2 = np.random.uniform(0, 1)

    return dict(q1=q1, q2=q2, mstar=mstar, rstar=rstar,
                injections=[dict(zip(labels, _))
                            for _ in zip(periods, t0s, radii, b, e, pomega)])


def slice_lcs(lcs, period, t0, rng=(-1, 1), bins=64):
    bin_edges = np.linspace(rng[0], rng[1], bins)

    n = np.zeros(len(bin_edges) - 1)
    mean = np.zeros(len(bin_edges) - 1)
    m2 = np.zeros(len(bin_edges) - 1)
    for lc in lcs:
        d = (lc.time - t0 + 0.5*period) % period - 0.5*period
        m = (rng[0] < d) * (d < rng[1])
        if np.any(m):
            x = lc.flux[m]
            x /= np.median(x)
            i = np.digitize(d[m], bin_edges) - 1
            n[i] += 1
            delta = x - mean[i]
            mean[i] += delta / n[i]
            m2[i] += delta * (x - mean[i])

    # Compute the online variance estimate.
    variance = np.zeros_like(m2)
    m = n > 1
    variance[m] = m2[m] / (n[m] - 1)

    return np.concatenate(([period, t0], mean, variance))


def extract_features(args):
    bins, pipe, q = args
    try:
        results = pipe.query(**q)
    except ValueError:
        return []

    features = []
    for body in results["injection"].bodies:
        features.append((1, slice_lcs(results["data"], body.period,
                                      body.t0, bins=bins)))
        features.append((-1, slice_lcs(results["data"], body.period,
                                       body.period * np.random.rand(),
                                       bins=bins)))
    return features


def main(N, K, bins):
    # Load the stellar dataset.
    stars = load_stars()

    # Set up the pipeline.
    pipe = setup_pipeline()

    # Generate N queries for the pipeline with injections in each one.
    queries = []
    for i in np.random.randint(len(stars), size=N):
        q = generate_system(K,
                            mstar=stars[i]["mstar"],
                            rstar=stars[i]["rstar"])
        q["kicid"] = stars[i]["kic"]
        queries.append((bins, pipe, q))

    pool = Pool()

    nmx = 2 * N * K
    nf = 2 + 2*(bins-1)
    with h5py.File("simulation.h5", "w") as f:
        tags_dset = f.create_dataset("tags", shape=(nmx, ), dtype=int)
        feat_dset = f.create_dataset("features", shape=(nmx, nf), dtype=float)

        n = 0
        for r in ifilter(len, pool.imap(extract_features, queries)):
            if not len(r):
                continue
            flag, feat = izip(*r)
            feat = np.vstack(feat)

            dn = len(flag)
            tags_dset[n:n+dn] = flag
            feat_dset[n:n+dn, :] = feat
            n += dn

            f.attrs["length"] = n

    pool.close()
    pool.join()


if __name__ == "__main__":
    np.random.seed(1234)

    N = 1000
    K = 10
    bins = 64
    main(N, K, bins)
