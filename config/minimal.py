root.detection.thresholdPolarity = "both"
root.detection.thresholdValue = 6

root.detection.background.isNanSafe = True

root.measurement.algorithms.names.clear()
for alg in ["shape.sdss", "flux.sinc", "flux.aperture"]:
    root.measurement.algorithms.names.add(alg)

root.measurement.algorithms["flux.aperture"].radii = [1, 2, 4, 8, 16] # pixels

root.measurement.slots.instFlux = None        # flux.gaussian
root.measurement.slots.modelFlux = None       # flux.gaussian
root.measurement.slots.psfFlux = None         # flux.psf
