import QtQuick
import QtMultimedia

// Live picture from the Facecam, loaded only while the Facecam page shows and
// no app streams from the camera. It asks for the smallest format, and being
// unloaded stops the camera so a call can take it. Kept in its own file so the
// panel still loads where Qt Multimedia is not installed.
Item {
  id: root
  property string product: ""
  readonly property bool running: camera.active
  property string errorText: ""

  MediaDevices { id: devices }

  function findDevice() {
    var inputs = devices.videoInputs
    for (var i = 0; i < inputs.length; i++) if (inputs[i].description === root.product) return inputs[i]
    return null
  }
  function smallestFormat(device) {
    var best = null
    for (var i = 0; i < device.videoFormats.length; i++) {
      var format = device.videoFormats[i]
      if (!best || format.resolution.width * format.resolution.height < best.resolution.width * best.resolution.height) best = format
    }
    return best
  }
  function start() {
    if (!root.product || camera.active) return
    var device = findDevice()
    if (!device) { root.errorText = "Qt does not list this camera"; return }
    camera.cameraDevice = device
    var format = smallestFormat(device)
    if (format) camera.cameraFormat = format
    camera.active = true
  }
  onProductChanged: start()
  Component.onCompleted: start()

  CaptureSession {
    camera: Camera {
      id: camera
      onErrorOccurred: function(error, errorString) { root.errorText = errorString || "The camera did not start" }
    }
    videoOutput: output
  }
  VideoOutput { id: output; anchors.fill: parent; fillMode: VideoOutput.PreserveAspectCrop }
}
