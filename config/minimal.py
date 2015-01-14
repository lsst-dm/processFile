if False:
    root.detection.thresholdPolarity = "both"
    root.detection.thresholdValue = 6

root.detection.background.isNanSafe = True

# The below requires pex_config of at least version 4e802877.
for stage in [root.calibrate.initialMeasurement, root.calibrate.measurement, root.measurement]:
    stage.plugins.names.clear()
    for alg in ["base_SdssCentroid", "base_SdssShape", "base_SincFlux", "base_CircularApertureFlux"]:
        stage.plugins.names.add(alg)

root.measurement.plugins['base_CircularApertureFlux'].radii=[1, 2, 4, 8, 16] # pixels

root.measurement.slots.instFlux = None
root.measurement.slots.modelFlux = None
root.measurement.slots.psfFlux = None

# Required for PSF measurement
for alg in ["base_PixelFlags", "base_PsfFlux"]:
    root.calibrate.initialMeasurement.plugins.names.add(alg)
