from __future__ import division, print_function, absolute_import, unicode_literals
#*****************************************************************
#    pyGSTi 0.9:  Copyright 2015 Sandia Corporation
#    This Software is released under the GPL license detailed
#    in the file "license.txt" in the top-level pyGSTi directory
#*****************************************************************
""" Functions for selecting a complete set of fiducials for a GST analysis."""

import numpy as _np
import scipy
from .. import objects as _objs
from .. import construction as _constr
from . import scoring as _scoring


def generate_fiducials(gs_target, gatesToOmit, maxFidLength=2,
                       algorithm='slack', algorithm_kwargs={}, verbosity=0):
    """Generate prep and measurement fiducials for a given target gateset.

    Parameters
    ----------
    gs_target : GateSet
        The gateset you are aiming to implement.

    gatesToOmit : list of string
        List of strings identifying gates in the gateset that should not be
        used in fiducials (a common example is the identity gate).

    maxFidLength : int
        The maximum number of gates to include in a fiducial.

    algorithm : {'greedy', 'slack'}, optional
        Specifies the algorithm to use to generate the fiducials. Current
        options are:

        'slack'
            See :func:`optimize_integer_fiducials_slack` for more details.

    algorithm_kwargs : dict
        Dictionary of ``{'keyword': keyword_arg}`` pairs providing keyword
        arguments for the specified `algorithm` function. See the documentation
        for functions referred to in the `algorithm` keyword documentation for
        what options are available for each algorithm.

    Returns
    -------
    prepFidList : list of GateString
        A list containing the gate sequences for the prep fiducials.

    measFidList : list of GateString
        A list containing the gate sequences for the measurement fiducials.

    """
    fidGates = [gate for gate in gs_target.gates if gate not in gatesToOmit]
    availableFidList = _constr.list_all_gatestrings(fidGates, 0, maxFidLength)

    if algorithm == 'slack':
        default_kwargs = {
                          'fidList': availableFidList,
                          'verbosity': verbosity,
                         }

        if ('slackFrac' not in algorithm_kwargs
                and 'fixedSlack' not in algorithm_kwargs):
            algorithm_kwargs['slackFrac'] = 1.0
        for key in default_kwargs:
            if key not in algorithm_kwargs:
                algorithm_kwargs[key] = default_kwargs[key]

        prepAlg_kwargs = algorithm_kwargs.copy()
        prepAlg_kwargs['prepOrMeas'] = 'prep'
        prepFidList = optimize_integer_fiducials_slack(gateset=gs_target,
                                                       **prepAlg_kwargs)

        measAlg_kwargs = algorithm_kwargs.copy()
        measAlg_kwargs['prepOrMeas'] = 'meas'
        measFidList = optimize_integer_fiducials_slack(gateset=gs_target,
                                                       **measAlg_kwargs)

    else:
        raise ValueError("'{}' is not a valid algorithm "
                         "identifier.".format(algorithm))

    return prepFidList, measFidList


#def bool_list_to_ind_list(boolList):
#    output = _np.array([])
#    for i, boolVal in boolList:
#        if boolVal == 1:
#            output = _np.append(i)
#    return output

def xor(*args):
    """Implements logical xor function for arbitrary number of inputs.

    Parameters
    ----------
    args : bool-likes
        All the boolean (or boolean-like) objects to be checked for xor
        satisfaction.

    Returns
    ---------
    output : bool
        True if and only if one and only one element of args is True and the
        rest are False.  False otherwise.

    """

    output = sum(bool(x) for x in args) == 1
    return output

def make_prep_mxs(gs,prepFidList):
    """Make a list of matrices for the gate set preparation operations.

    Makes a list of matrices, where each matrix corresponds to a single
    preparation operation in the gate set, and the column of each matrix is a
    fiducial acting on that state preparation.

    Parameters
    ----------
    gs : GateSet
        The gate set (associates gate matrices with gate labels).

    prepFidList : list of GateStrings
        List of fiducial gate sequences for preparation.

    Returns
    ----------
    outputMatList : list of arrays
        List of arrays, where each array corresponds to one preparation in the
        gate set, and each column therein corresponds to a single fiducial.

    """

    dimRho = gs.get_dimension()
    #numRho = len(gs.preps)
    numFid = len(prepFidList)
    outputMatList = []
    for rho in list(gs.preps.values()):
        outputMat = _np.zeros([dimRho, numFid],float)
        counter = 0
        for prepFid in prepFidList:
            outputMat[:,counter] = _np.dot(gs.product(prepFid),rho).T[0]
            counter += 1
        outputMatList.append(outputMat)
    return outputMatList

def make_meas_mxs(gs,prepMeasList):
    """Make a list of matrices for the gate set measurement operations.

    Makes a list of matrices, where each matrix corresponds to a single
    measurement effect in the gate set, and the column of each matrix is the
    transpose of the measurement effect acting on a fiducial.

    Parameters
    ----------
    gs : GateSet
        The gate set (associates gate matrices with gate labels).

    measFidList : list of GateStrings
        List of fiducial gate sequences for measurement.

    Returns
    ----------
    outputMatList : list of arrays
        List of arrays, where each array corresponds to one measurement in the
        gate set, and each column therein corresponds to a single fiducial.

    """

    dimE = gs.get_dimension()
    # numE = len(gs.effects)
    numFid = len(prepMeasList)
    outputMatList = []
    for E in list(gs.effects.values()):
        outputMat = _np.zeros([dimE,numFid],float)
        counter = 0
        for measFid in prepMeasList:
            outputMat[:,counter] = _np.dot(E.T,gs.product(measFid))[0]
            counter += 1
        outputMatList.append(outputMat)
    return outputMatList

def test_fiducial_list(gateset, fidList, prepOrMeas, scoreFunc='all',
                       returnAll=False, threshold=1e6):
    """Tests a prep or measure fiducial list for informational completeness.

    Parameters
    ----------
    gateset : GateSet
        The gate set (associates gate matrices with gate labels).

    fidList : list of GateStrings
        List of fiducial gate sequences to test.

    prepOrMeas : string ("prep" or "meas")
        Are we testing preparation or measurement fiducials?

    scoreFunc : str ('all' or 'worst'), optional (default is 'all')
        Sets the objective function for scoring a fiducial set.  If 'all',
        score is (number of fiducials) * sum(1/Eigenvalues of score matrix).
        If 'worst', score is (number of fiducials) * 1/min(Eigenvalues of score
        matrix).  Note:  Choosing 'worst' corresponds to trying to make the
        optimizer make the "worst" direction (the one we are least sensitive to
        in Hilbert-Schmidt space) as minimally bad as possible.  Choosing 'all'
        corresponds to trying to make the optimizer make us as sensitive as
        possible to all directions in Hilbert-Schmidt space.  (Also note-
        because we are using a simple integer program to choose fiducials, it
        is possible to get stuck in a local minimum, and choosing one or the
        other objective function can help avoid such minima in different
        circumstances.)

    returnAll : bool, optional (default is False)
        If true, function returns reciprocals of eigenvalues of fiducial score
        matrix, and the score of the fiducial set as specified by scoreFunc, in
        addition to a boolean specifying whether or not the fiducial set is
        informationally complete

    threshold : float, optional (default is 1e6)
        Specifies a maximum score for the score matrix, above which the
        fiducial set is rejected as informationally incomplete.

    Returns
    -------
    testResult : bool
        Whether or not the specified fiducial list is informationally complete
        for the provided gate set, to within the tolerance specified by
        threshold.

    spectrum : array, optional
        The number of fiducials times the reciprocal of the spectrum of the
        score matrix.  Only returned if returnAll == True.

    score : float, optional
        The score for the fiducial set; only returned if returnAll == True.

    """

    # nFids = len(fidList)

    dimRho = gateset.get_dimension()

    # fidLengths = _np.array( list(map(len,fidList)), 'i')
    if prepOrMeas == 'prep':
        fidArrayList = make_prep_mxs(gateset,fidList)
    elif prepOrMeas == 'meas':
        fidArrayList = make_meas_mxs(gateset,fidList)
    else:
        raise ValueError('Invalid value "{}" for prepOrMeas (must be "prep" '
                         'or "meas")!'.format(prepOrMeas))
    numMxs = len(fidArrayList)

    numFids = len(fidList)
    scoreMx = _np.zeros([dimRho,numFids *  numMxs],float)
    colInd = 0
#    wts = _np.array(wts)
#    wtsLoc = _np.where(wts)[0]
    for fidArray in fidArrayList:
        scoreMx[:,colInd:colInd+numFids] = fidArray
        colInd += numFids
    scoreSqMx = _np.dot(scoreMx,scoreMx.T)
    spectrum = _np.linalg.eigvalsh(scoreSqMx)
    score = numFids * _scoring.list_score(_np.abs(spectrum), scoreFunc)

    if (score <= 0 or _np.isinf(score)) or score > threshold:
        testResult = False
    else:
        testResult = True

    return (testResult, spectrum, score) if returnAll else testResult


def build_bitvec_mx(n, k):
    """Create an array of all fixed length and Hamming weight binary vectors.

    Parameters
    ----------
    n : int
        The length of each bit string.
    k : int
        The hamming weight of each bit string.

    Returns
    ----------
    bitVecMx : _np array
        this is the array of binary vectors of a fixed length n and fixed
        Hamming weight k.

    """
    bitVecMx = _np.zeros([int(scipy.special.binom(n, k)), n])
    diff = n - k

    # Recursive function for populating a matrix of arbitrary size
    def build_mx(previous_bit_locs, i, counter):
        """Allows arbitrary nesting of for loops

        Parameters
        ----------
        previous_bit_locs : tuple
            current loop contents, ex:

            >>> for i in range(10):
            >>>    for j in range(10):
            >>>        (i, j)

        i : int
            Loop depth

        counter : int
            tracks which fields of mx have been already set

        Returns
        ----------
        counter : int
            for updating the counter one loop above the current one

        """
        if i == 0:
            bitVecMx[counter][[previous_bit_locs]] = 1
            counter += 1
        else:
            subK = k - i
            # Recursive definition allowing arbitrary size
            last_bit_loc = previous_bit_locs[-1] # More explicit?
            for bit_loc in range(1+last_bit_loc, diff+subK+1):
                current_bit_locs = previous_bit_locs + (bit_loc,)

                counter = build_mx(current_bit_locs, i - 1, counter)

        # An alternative to shared state
        return counter

    counter = 0
    for bit_loc_0 in range(diff+1):
        counter = build_mx((bit_loc_0,), k - 1, counter) # Do subK additional iterations

    return bitVecMx

def optimize_integer_fiducials_slack(gateset, fidList, prepOrMeas=None,
                                     initialWeights=None, scoreFunc='all',
                                     maxIter=100, fixedSlack=None,
                                     slackFrac=None, returnAll=False,
                                     forceEmpty=True, forceEmptyScore=1e100,
                                     fixedNum=None, threshold=1e6,
                                     # forceMinScore=1e100,
                                     verbosity=1):
    """Find a locally optimal subset of the fiducials in fidList.

    Locally optimal here means that no single fiducial can be excluded without
    increasing the sum of the reciprocals of the singular values of the "score
    matrix" (the matrix whose columns are the fiducials acting on the
    preparation, or the transpose of the measurement acting on the fiducials),
    by more than a fixed or variable amount of "slack", as specified by
    fixedSlack or slackFrac.

    Parameters
    ----------
    gateset : GateSet
        The gate set (associates gate matrices with gate labels).

    fidList : list of GateStrings
        List of all fiducials gate sequences to consider.

    initialWeights : list-like
        List or array of either booleans or (0 or 1) integers specifying which
        fiducials in fidList comprise the initial fiduial set.  If None, then
        starting point includes all fiducials.

    scoreFunc : str ('all' or 'worst'), optional (default is 'all')
        Sets the objective function for scoring a fiducial set.  If 'all',
        score is (number of fiducials) * sum(1/Eigenvalues of score matrix).
        If 'worst', score is (number of fiducials) * 1/min(Eigenvalues of score
        matrix).  Note:  Choosing 'worst' corresponds to trying to make the
        optimizer make the "worst" direction (the one we are least sensitive to
        in Hilbert-Schmidt space) as minimally bad as possible.  Choosing 'all'
        corresponds to trying to make the optimizer make us as sensitive as
        possible to all directions in Hilbert-Schmidt space.  (Also note-
        because we are using a simple integer program to choose fiducials, it
        is possible to get stuck in a local minimum, and choosing one or the
        other objective function can help avoid such minima in different
        circumstances.)

    maxIter : int, optional
        The maximum number of iterations before stopping.

    fixedSlack : float, optional
        If not None, a floating point number which specifies that excluding a
        fiducial is allowed to increase the fiducial set score additively by
        fixedSlack.  You must specify *either* fixedSlack or slackFrac.

    slackFrac : float, optional
        If not None, a floating point number which specifies that excluding a
        fiducial is allowed to increase the fiducial set score multiplicatively
        by (1+slackFrac).  You must specify *either* fixedSlack or slackFrac.

    returnAll : bool, optional
        If True, return the final "weights" vector and score dictionary in
        addition to the optimal fiducial list (see below).

    forceEmpty : bool, optional (default is True)
        Whether or not to force all fiducial sets to contain the empty gate
        string as a fiducial.

        IMPORTANT:  This only works if the first element of fidList is the
        empty gate string.

    forceEmptyScore : float, optional (default is 1e100)
        When forceEmpty is True, what score to assign any fiducial set that
        does not contain the empty gate string as a fiducial.

    forceMin : bool, optional (default is False)
        If True, forces fiducial selection to choose a fiducial set that is *at
        least* as large as forceMinNum.

    forceMinNum : int, optional (default is None)
        If not None, and forceMin == True, the minimum size of the returned
        fiducial set.

    forceMinScore : float, optional (default is 1e100)
        When forceMin is True, what score to assign any fiducial set that does
        not contain at least forceMinNum fiducials.

    threshold : float, optional (default is 1e6)
        Entire fiducial list is first scored before attempting to select
        fiducials; if score is above threshold, then fiducial selection will
        auto-fail.  If final fiducial set selected is above threshold, then
        fiducial selection will print a warning, but return selected set.

    verbosity : int, optional
        Integer >= 0 indicating the amount of detail to print.

    Returns
    -------
    finalFidList : list
        Sublist of fidList specifying the final, optimal, set of fiducials.

    weights : array
        Integer array, of length len(fidList), containing 0s and 1s to indicate
        which elements of fidList were chosen as finalFidList.  Only returned
        when returnAll == True.

    scoreDictionary : dict
        Dictionary with keys == tuples of 0s and 1s of length len(fidList),
        specifying a subset of fiducials, and values == 1.0/smallest-non-gauge-
        eigenvalue "scores".

    """
    printer = _objs.VerbosityPrinter.build_printer(verbosity)

    if not xor(fixedSlack,slackFrac):
        raise ValueError("One and only one of fixedSlack or slackFrac should be specified")

    initial_test = test_fiducial_list(gateset, fidList, prepOrMeas,
                                      scoreFunc=scoreFunc, returnAll=True,
                                      threshold=threshold)
    if initial_test[0]:
        print("Complete initial fiducial set succeeds.")
        print("Now searching for best fiducial set.")
    else:
        print("Complete initial fiducial set FAILS.")
        print("Aborting search.")
        return None

    #Initially allow adding to weight. -- maybe make this an argument??
    lessWeightOnly = False

    nFids = len(fidList)

    dimRho = gateset.get_dimension()

    printer.log("Starting fiducial set optimization. Lower score is better.")

    scoreD = {}

    #fidLengths = _np.array( list(map(len,fidList)), 'i')
    if prepOrMeas == 'prep':
        fidArrayList = make_prep_mxs(gateset,fidList)
    elif prepOrMeas == 'meas':
        fidArrayList = make_meas_mxs(gateset,fidList)
    else:
        raise Exception('prepOrMeas must be specified!')
    numMxs = len(fidArrayList)

    def compute_score(wts,cache_score = True):
        score = None
        if forceEmpty and _np.count_nonzero(wts[:1]) != 1:
            score = forceEmptyScore
#        if forceMinNum and _np.count_nonzero(wts) < forceMinNum:
#            score = forceMinScore
        if score is None:
            numFids = _np.sum(wts)
            scoreMx = _np.zeros([dimRho,int(numFids) *  int(numMxs)], float)
            colInd = 0
            wts = _np.array(wts)
            wtsLoc = _np.where(wts)[0]
            for fidArray in fidArrayList:
                scoreMx[:,colInd:colInd+int(numFids)] = fidArray[:,wtsLoc]
                colInd += numFids
            scoreSqMx = _np.dot(scoreMx,scoreMx.T)
#            score = numFids * _np.sum(1./_np.linalg.eigvalsh(scoreSqMx))
            score = numFids * _scoring.list_score(
                                            _np.linalg.eigvalsh(scoreSqMx),
                                            scoreFunc)
            if score <= 0 or _np.isinf(score):
                score = 1e10
        if cache_score:
            scoreD[tuple(wts)] = score
        return score

    if not (fixedNum is None):
        if forceEmpty:
            hammingWeight = fixedNum - 1
            numBits = len(fidList) - 1
        else:
            hammingWeight = fixedNum
            numBits = len(fidList)
        numFidLists = scipy.special.binom(numBits,hammingWeight)
        printer.log("Output set is required to be of size%s" % fixedNum)
        printer.log("Total number of fiducial sets to be checked is%s" % numFidLists)
        printer.warning("If this is very large, you may wish to abort.")
#        print "Num bits:", numBits
#        print "Num Fid Options:", hammingWeight
        # Now a non auxillary function:
        bitVecMat = build_bitvec_mx(numBits, hammingWeight)

        if forceEmpty:
            bitVecMat = _np.concatenate((_np.array([[1]*int(numFidLists)]).T,bitVecMat),axis=1)
        best_score = _np.inf
        # Explicitly declare best_weights, even if it will soon be replaced
        best_weights = []
        for weights in bitVecMat:
            temp_score = compute_score(weights,cache_score = True)
            # If scores are within machine precision, we want the fiducial set
            # that requires fewer total button gate operations.
            if abs(temp_score - best_score) < 1e-8:
#                print "Within machine precision!"
                bestFidList = []
                for index, val in enumerate(best_weights):
                    if val==1:
                        bestFidList.append(fidList[index])
                tempFidList = []
                for index, val in enumerate(weights):
                    if val == 1:
                        tempFidList.append(fidList[index])
                tempLen = sum(len(i) for i in tempFidList)
                bestLen = sum(len(i) for i in bestFidList)
#                print tempLen, bestLen
#                print temp_score, best_score
                if tempLen < bestLen:
                    best_score = temp_score
                    best_weights = weights
                    printer.log("Switching!")
            elif temp_score < best_score:
                best_score = temp_score
                best_weights = weights

        goodFidList = []
        weights = best_weights
        for index, val in enumerate(weights):
            if val==1:
                goodFidList.append(fidList[index])

        if returnAll:
            return goodFidList, weights, scoreD
        else:
            return goodFidList


        return best_score, best_weights, finalFidList #pylint: disable=undefined-variable

    def get_neighbors(boolVec):
        for i in range(nFids):
            v = boolVec.copy()
            v[i] = (v[i] + 1) % 2 #toggle v[i] btwn 0 and 1
            yield v

    if initialWeights is not None:
        weights = _np.array( [1 if x else 0 for x in initialWeights ] )
    else:
        weights = _np.ones( nFids, 'i' ) #default: start with all germs
        lessWeightOnly = True #we're starting at the max-weight vector

    score = compute_score(weights)
    L1 = sum(weights) # ~ L1 norm of weights

    with printer.progress_logging(1):

        for iIter in range(maxIter):
            scoreD_keys = scoreD.keys() #list of weight tuples already computed

            printer.show_progress(iIter, maxIter-1,
                                  suffix="score=%g, nFids=%d" % (score, L1))

            bFoundBetterNeighbor = False
            for neighbor in get_neighbors(weights):
                if tuple(neighbor) not in scoreD_keys:
                    neighborL1 = sum(neighbor)
                    neighborScore = compute_score(neighbor)
                else:
                    neighborL1 = sum(neighbor)
                    neighborScore = scoreD[tuple(neighbor)]

                # Move if we've found better position; if we've relaxed, we
                # only move when L1 is improved.
                if neighborScore <= score and (neighborL1 < L1
                                               or lessWeightOnly == False):
                    weights, score, L1 = neighbor, neighborScore, neighborL1
                    bFoundBetterNeighbor = True
                    printer.log("Found better neighbor: nFids = %d score = %g"
                                % (L1,score), 2)


            if not bFoundBetterNeighbor: # Time to relax our search.
                # from now on, don't allow increasing weight L1
                lessWeightOnly=True

                if fixedSlack:
                    # Note score is positive (for sum of 1/lambda)
                    slack = score + fixedSlack
                elif slackFrac:
                    slack = score * slackFrac
                assert(slack > 0)

                printer.log("No better neighbor. "
                            "Relaxing score w/slack: %g => %g"
                            % (score, score+slack), 2)
                # artificially increase score and see if any neighbor is better
                # now...
                score += slack

                for neighbor in get_neighbors(weights):
                    if sum(neighbor) < L1 and scoreD[tuple(neighbor)] < score:
                        weights, score, L1 = (neighbor,
                                              scoreD[tuple(neighbor)],
                                              sum(neighbor))
                        bFoundBetterNeighbor = True
                        printer.log("Found better neighbor: nFids = %d "
                                    "score = %g" % (L1, score), 2)

                if not bFoundBetterNeighbor: #Relaxing didn't help!
                    printer.log("Stationary point found!")
                    break # end main for loop

            printer.log("Moving to better neighbor")
        else:
            printer.log("Hit max. iterations")

    printer.log("score = %s"       % score)
    printer.log("weights = %s"     % weights)
    printer.log("L1(weights) = %s" % sum(weights))

    goodFidList = []
    for index,val in enumerate(weights):
        if val==1:
            goodFidList.append(fidList[index])

    # final_test = test_fiducial_list(gateset, goodFidList, prepOrMeas,
    #                                 scoreFunc=scoreFunc, returnAll=True,
    #                                 threshold=threshold)
    if initial_test[0]:
        print("Final fiducial set succeeds.")
    else:
        print("WARNING: Final fiducial set FAILS.")

    if returnAll:
        return goodFidList, weights, scoreD
    else:
        return goodFidList
