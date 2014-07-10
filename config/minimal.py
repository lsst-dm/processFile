if False:
    root.detection.thresholdPolarity = "both"
    root.detection.thresholdValue = 6

root.detection.background.isNanSafe = True

for stage in [root.calibrate.initialMeasurement, root.calibrate.measurement, root.measurement]:
    stage.algorithms.names.clear()
    for alg in ["shape.sdss", "flux.sinc", "flux.aperture"]:
        stage.algorithms.names.add(alg)

root.measurement.algorithms["flux.aperture"].radii = [1, 2, 4, 8, 16] # pixels

root.measurement.slots.instFlux = None        # flux.gaussian
root.measurement.slots.modelFlux = None       # flux.gaussian
root.measurement.slots.psfFlux = None         # flux.psf

# required by the PSF algorithms we chose
for alg in ["flux.gaussian", "flux.psf", "flags.pixel"]:
    root.calibrate.initialMeasurement.algorithms.names.add(alg) 
