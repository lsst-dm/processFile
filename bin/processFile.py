#!/usr/bin/env python

#
# LSST Data Management System
# Copyright 2008-2015 AURA/LSST.
#
# This product includes software developed by the
# LSST Project (http://www.lsst.org/).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the LSST License Statement and
# the GNU General Public License along with this program.  If not,
# see <http://www.lsstcorp.org/LegalNotices/>.
#

import os
import re
import sys
import numpy as np

import eups
import lsst.daf.base               as dafBase
import lsst.pex.logging            as pexLog
import lsst.afw.coord              as afwCoord
import lsst.afw.geom               as afwGeom
import lsst.afw.image              as afwImage
import lsst.afw.math               as afwMath
import lsst.afw.table              as afwTable
import lsst.afw.display.ds9        as ds9
import lsst.meas.algorithms        as measAlg
import lsst.pex.config             as pexConfig

from lsst.ip.isr import IsrTask
from lsst.pipe.tasks.calibrate import CalibrateTask
from lsst.meas.algorithms.detection import SourceDetectionTask
try:
    from lsst.meas.deblender import SourceDeblendTask
except ImportError:
    SourceDeblendTask = None
from lsst.meas.base import SingleFrameMeasurementTask

class MyIsrConfig(IsrTask.ConfigClass):
    """A version of IsrTask.ConfigClass that disables almost everything
    The interpolation code is still run"""
    
    def __init__(self, *args, **kwargs):
        IsrTask.ConfigClass.__init__(self, *args, **kwargs)
        self.doBias = False
        self.doDark = False
        self.doFlat = False
        self.doFringe = False
        self.doAssembleCcd = False

class ProcessFileConfig(pexConfig.Config):
    """A container for the Configs that ProcessFile needs

Using such a container allows us to use the standard -c/-C/--show config options that pipe_base provides
"""
    variance = pexConfig.Field(dtype=float, default=np.nan,
                               doc="Initial per-pixel variance (if <= 0, estimate from inputs)")
    badPixelValue = pexConfig.Field(dtype=float, default=np.nan, doc="Value indicating a bad pixel")
    interpPlanes = pexConfig.ListField(
        dtype = str, default = ["BAD",],
        doc = "Names of mask planes to interpolate over (e.g. ['BAD', 'SAT'])",
        itemCheck = lambda x: x in afwImage.MaskU().getMaskPlaneDict().keys())
    isr = MyIsrConfig()
    doCalibrate = pexConfig.Field(dtype=bool, default=True, doc="Calibrate input data?")
    calibrate = pexConfig.ConfigField(dtype=CalibrateTask.ConfigClass,
                                      doc=CalibrateTask.ConfigClass.__doc__)
    detection = pexConfig.ConfigField(dtype=SourceDetectionTask.ConfigClass,
                                      doc=SourceDetectionTask.ConfigClass.__doc__)
    measurement = pexConfig.ConfigField(dtype=SingleFrameMeasurementTask.ConfigClass,
                                        doc=SingleFrameMeasurementTask.ConfigClass.__doc__)
    doDeblend = pexConfig.Field(dtype=bool, default=True, doc="Deblend sources?")
    if SourceDeblendTask:
        deblend = pexConfig.ConfigField(dtype=SourceDeblendTask.ConfigClass,
                                        doc=SourceDeblendTask.ConfigClass.__doc__)
    
def run(config, inputFiles, weightFiles=None, varianceFiles=None,
        returnCalibSources=False, display=False, verbose=False):
    #
    # Create the tasks
    #
    schema = afwTable.SourceTable.makeMinimalSchema()
    algMetadata = dafBase.PropertyList()

    isrTask = IsrTask(config=config.isr)
    calibrateTask =         CalibrateTask(config=config.calibrate)
    sourceDetectionTask =   SourceDetectionTask(config=config.detection, schema=schema)
    if config.doDeblend:
        if SourceDeblendTask:
            sourceDeblendTask = SourceDeblendTask(config=config.deblend, schema=schema)
        else:
            print >> sys.stderr, "Failed to import lsst.meas.deblender;  setting doDeblend = False"
            config.doDeblend = False

    sourceMeasurementTask = SingleFrameMeasurementTask(config=config.measurement,
                                                       schema=schema, algMetadata=algMetadata)

    exposureDict = {}; calibSourcesDict = {}; sourcesDict = {}
    
    for inputFile, weightFile, varianceFile in zip(inputFiles, weightFiles, varianceFiles):
        #
        # Create the output table
        #
        tab = afwTable.SourceTable.make(schema)
        #
        # read the data
        #
        if verbose:
            print "Reading %s" % inputFile
            
        exposure = makeExposure(inputFile, weightFile, varianceFile,
                                config.badPixelValue, config.variance)
        #
        if config.interpPlanes:
            import lsst.ip.isr as ipIsr
            defects = ipIsr.getDefectListFromMask(exposure.getMaskedImage(), config.interpPlanes,
                                                  growFootprints=0)

            isrTask.run(exposure, defects=defects)
        #
        # process the data
        #
        calibSources = None                 # sources used to calibrate the frame (photom, astrom, psf)
        if config.doCalibrate:
            result = calibrateTask.run(exposure)
            exposure, sources = result.exposure, result.sources

            if returnCalibSources:
                calibSources = sources
        else:
            if not exposure.getPsf():
                calibrateTask.installInitialPsf(exposure)

        exposureDict[inputFile] = exposure
        calibSourcesDict[inputFile] = calibSources

        result = sourceDetectionTask.run(tab, exposure)
        sources = result.sources
        sourcesDict[inputFile] = sources

        if config.doDeblend:
            sourceDeblendTask.run(exposure, sources, exposure.getPsf())

        sourceMeasurementTask.measure(exposure, sources)

        if verbose:
            print "Detected %d objects" % len(sources)

        if display:                         # display on ds9 (see also --debug argparse option)
            if algMetadata.exists("base_CircularApertureFlux_radii"):
                radii = algMetadata.get("base_CircularApertureFlux_radii")
            else:
                radii = None

            frame = 1
            ds9.mtv(exposure, title=os.path.split(inputFile)[1], frame=frame)

            with ds9.Buffering():
                for s in sources:
                    xy = s.getCentroid()
                    ds9.dot('+', *xy, ctype=ds9.CYAN if s.get("flags_negative") else ds9.GREEN, frame=frame)
                    ds9.dot(s.getShape(), *xy, ctype=ds9.RED, frame=frame)

                    if radii:
                        for radius in radii:
                            ds9.dot('o', *xy, size=radius, ctype=ds9.YELLOW, frame=frame)

    return exposureDict, calibSourcesDict, sourcesDict

def makeExposure(inputFile, weightFile, varianceFile, badPixelValue, variance):
    exposure = afwImage.ExposureF(inputFile)

    if np.isfinite(badPixelValue):
        mi = exposure.getMaskedImage()
        bad = mi.getImage().getArray() == badPixelValue
        mi.getMask().getArray()[bad] |= mi.getMask().getPlaneBitMask("BAD")
        del bad; del mi

    if weightFile or varianceFile:
        assert(not (weightFile and varianceFile)) # we checked this earlier

        assert not np.isfinite(variance), \
            "Please don't specify a variance and %s file" % ("weight" if weightFile else "variance")

        mi = exposure.getMaskedImage()

        if weightFile:
            variance = afwImage.ImageF(weightFile)

            varr = variance.getArray()
            bad = (varr == 0)
            varr[bad] = np.inf # avoid numpy warning
            varr[:] = 1/varr
        else:
            variance = afwImage.ImageF(varianceFile)
            bad = np.logical_not(np.isfinite(mi.getImage().getArray()))

        mi.getMask().getArray()[bad] |= mi.getMask().getPlaneBitMask("BAD")
        del bad

        mi.getVariance()[:] = variance
        del mi
    else:
        if not np.isfinite(variance) or variance <= 0:
            mi = exposure.getMaskedImage()

            sctrl = afwMath.StatisticsControl()
            sctrl.setAndMask(mi.getMask().getPlaneBitMask("BAD"))
            variance = afwMath.makeStatistics(mi, afwMath.VARIANCECLIP, sctrl).getValue()
            del sctrl; del mi

        exposure.getMaskedImage().getVariance()[:] = variance

    return exposure

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

if __name__ == "__main__":
    import argparse
    import lsst.pipe.base.argumentParser as pbArgparse

    # Note that argparse doesn't actually respect the newlines in the help message below.
    parser = argparse.ArgumentParser(description="Process a fits file, detecting and measuring sources")
    parser.add_argument('inputFile', help="""File to process.

If inputFile contains a %%s it is taken to be a template and is expanded using the values of args.filters

If the inputFile FITS file has a 'VARIANCE' extension, then that extension will be used for the variance image.
    """)
    parser.add_argument('--weightFile', help="""File containing pixel "weights" (inverse variances)

If weightFile contains a %%s it is taken to be a template and is expanded using the values of args.filters.  Requires that inputFile also have a %%s.
Setting this option will override any included 'VARIANCE' image extension in inputFile.
    """)
    parser.add_argument('--varianceFile', help="""File containing pixel variances

If varianceFile contains a %%s it is taken to be a template and is expanded using the values of args.filters.  Requires that inputFile also have a %%s.
Setting this option will override any included 'VARIANCE' image extension in inputFile.
    """)
    parser.add_argument('--filters', nargs="+", help="List of filters to process", default="")
    parser.add_argument('--outputCatalog', nargs="?", help="Output catalogue")
    parser.add_argument('--outputCalibCatalog', nargs="?", help="Output catalogue of calibration objects")
    parser.add_argument('--outputCalexp', nargs="?", help="""Output calibrated exposure.
Also includes the PSF model and detection masks.
    """)

    parser.add_argument("-c", "--config", nargs="*", action=pbArgparse.ConfigValueAction,
                        help="config override(s), e.g. -c foo=newfoo bar.baz=3", metavar="NAME=VALUE")
    parser.add_argument("-C", "--configfile", dest="configfile", nargs="*",
                        action=pbArgparse.ConfigFileAction, help="config override file(s)")
    parser.add_argument("--show", nargs="+", default=(),
                        help="display the specified information to stdout and quit (unless run is specified).")
    parser.add_argument("-L", "--loglevel", help="logging level", default="WARN")
    parser.add_argument("-T", "--trace", nargs="*", action=pbArgparse.TraceLevelAction,
                        help="trace level for component", metavar="COMPONENT=LEVEL")

    parser.add_argument('--debug', '-d', action="store_true", help="Load debug.py?", default=False)
    parser.add_argument('--ds9', action="store_true", help="Display sources on ds9", default=False)
    parser.add_argument('--verbose', '-v', action="store_true", help="Be chatty?", default=False)

    #-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    #
    # Create the configs
    #
    config = ProcessFileConfig()

    config.calibrate.doAstrometry = False
    config.calibrate.doPhotoCal = False
    config.calibrate.detection.reEstimateBackground = False
    config.detection.returnOriginalFootprints=False

    #-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

    args = argparse.Namespace()
    args.config = config
    args = parser.parse_args(namespace=args)

    try:
        pbArgparse.obeyShowArgument(args.show, args.config, exit=True)
    except AttributeError:
        pass

    if args.debug:
        try:
            import debug
        except ImportError as e:
            print >> sys.stderr, e

    if args.loglevel:
        permitted = ('DEBUG', 'INFO', 'WARN', 'FATAL')
        if args.loglevel.upper() in permitted:
            value = getattr(pexLog.Log, args.loglevel.upper())
        else:
            try:
                value = int(args.loglevel)
            except ValueError:
                print >> sys.stderr, "log-level=%s not int or one of %s" % (args.loglevel, permitted)
                sys.exit(1)

        pexLog.Log.getDefaultLog().setThreshold(value)

    if args.weightFile and args.varianceFile:
        print >> sys.stderr, "Please only specify a weight *or* a variance"
        sys.exit(1)

    if re.search(r"%s", args.inputFile):
        inputFiles = [args.inputFile % f for f in args.filters]
        weightFiles = [args.weightFile % f for f in args.filters] if args.weightFile else None
        varianceFiles = [args.varianceFile % f for f in args.filters] if args.varianceFile else None

        if args.outputCalexp:
            args.outputCalexp = [args.outputCalexp % f for f in args.filters]
        if args.outputCalibCatalog:
            args.outputCalibCatalog = [args.outputCalibCatalog % f for f in args.filters]
        if args.outputCatalog:
            args.outputCatalog = [args.outputCatalog % f for f in args.filters]
    else:
        inputFiles = [args.inputFile]
        weightFiles = [args.weightFile if args.weightFile else None]
        varianceFiles = [args.varianceFile if args.varianceFile else None]

        if args.outputCalexp:
            args.outputCalexp = [args.outputCalexp]
        if args.outputCalibCatalog:
            args.outputCalibCatalog = [args.outputCalibCatalog]
        if args.outputCatalog:
            args.outputCatalog = [args.outputCatalog]

    exposureDict, calibSourcesDict, sourcesDict = run(config, inputFiles,
                                                      weightFiles=weightFiles, varianceFiles=varianceFiles,
                                                      returnCalibSources=args.outputCalibCatalog != None,
                                                      display=args.ds9, verbose=args.verbose)
    try:
        import lsst.processFile.version
        version = lsst.processFile.version.__version__
    except ImportError:
        print >> sys.stderr, "Unable to deduce processFile's version -- did you run scons?"
        version = "???"
    #
    # Write output files
    #
    for i, inputFile in enumerate(inputFiles):
        exposure = exposureDict[inputFile]
        calibSources = calibSourcesDict[inputFile]
        sources = sourcesDict[inputFile]

        exposure.getMetadata().set("VERSION", version)

        if args.outputCalexp:
            exposure.writeFits(args.outputCalexp[i])
        if args.outputCalibCatalog:
            calibSources.writeFits(args.outputCalibCatalog[i])
        if args.outputCatalog:
            sources.writeFits(args.outputCatalog[i])
