import QtQuick
import qs.Commons
import qs.Ui

// The Facecam page's stage: the live preview (or why there is none), what the
// camera is doing, the privacy switch, and the saved presets.
Column {
  id: root
  property var camera: null
  property var panel: null
  property var presets: []
  property string activePreset: ""
  // The panel is open on the Facecam page.
  property bool shown: false
  property bool previewOn: false
  property bool naming: false
  readonly property bool editing: nameField.activeFocus
  readonly property bool cameraLive: camera !== null && camera.live === true
  readonly property bool privacy: camera !== null && camera.privacy === true
  readonly property string appName: camera && camera.apps && camera.apps.length ? camera.apps.join(", ") : ""
  // Arguments for `elgato-control facecam`.
  signal command(var arguments)
  signal editingDone()
  spacing: Style.space(10)

  // The preview takes the camera, so it starts only while no app streams. It
  // then stays up until the page closes: while it streams, the camera can only
  // be live because of the preview itself.
  function updatePreview() {
    if (!shown || camera === null) previewOn = false
    else if (!cameraLive) previewOn = true
  }
  onShownChanged: updatePreview()
  onCameraLiveChanged: updatePreview()
  onCameraChanged: updatePreview()

  function isActive(name) { return root.activePreset !== "" && String(name).toLowerCase() === root.activePreset.toLowerCase() }
  function glyph(code) { return String.fromCodePoint(code) }
  function stopNaming() { root.naming = false; nameField.text = ""; root.editingDone() }
  function savePreset() {
    var name = nameField.text.trim()
    if (name !== "") root.command(["save-preset", name])
    root.stopNaming()
  }
  function overlay() {
    if (root.privacy) return { glyph: 0xF1737, title: "PRIVACY ON", detail: "The camera sends a blank picture", color: Color.accent }
    if (!root.previewOn) {
      if (root.cameraLive) return { glyph: 0xF05A0, title: root.appName ? "LIVE IN " + root.appName.toUpperCase() : "LIVE", detail: "The preview returns when the camera is free", color: Color.urgent }
      return { glyph: 0xF05A0, title: "PREVIEW OFF", detail: "", color: Color.muted }
    }
    if (preview.status === Loader.Error) return { glyph: 0xF05A0, title: "NO PREVIEW", detail: "Install qt6-multimedia for a live preview", color: Color.muted }
    if (preview.item && preview.item.errorText) return { glyph: 0xF05A0, title: "NO PREVIEW", detail: preview.item.errorText, color: Color.muted }
    if (!preview.item || !preview.item.running) return { glyph: 0xF05A0, title: "STARTING PREVIEW…", detail: "", color: Color.muted }
    return null
  }

  Text { anchors.horizontalCenter: parent.horizontalCenter; text: (root.camera ? root.camera.label : "Facecam").toUpperCase(); textFormat: Text.PlainText; color: Color.muted; font.family: Style.font.family; font.pixelSize: 10; font.bold: true }

  Rectangle {
    width: parent.width; height: Math.round(width * 9 / 16); radius: 0; clip: true
    color: "#000000"; border.color: root.panel ? root.panel.controlBorder : Color.muted
    Loader {
      id: preview
      anchors.fill: parent; anchors.margins: 1
      active: root.previewOn
      source: Qt.resolvedUrl("FacecamPreview.qml")
      onLoaded: item.product = Qt.binding(function() { return root.camera ? root.camera.product : "" })
    }
    Column {
      readonly property var info: root.overlay()
      visible: info !== null; anchors.centerIn: parent; width: parent.width - Style.space(24); spacing: Style.space(6)
      Text { anchors.horizontalCenter: parent.horizontalCenter; text: parent.info ? root.glyph(parent.info.glyph) : ""; color: parent.info ? parent.info.color : Color.muted; font.family: Style.font.family; font.pixelSize: 40 }
      Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: parent.info ? parent.info.title : ""; textFormat: Text.PlainText; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 11; font.bold: true }
      Text { visible: text !== ""; width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; text: parent.info ? parent.info.detail : ""; textFormat: Text.PlainText; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9 }
    }
  }

  Row {
    width: parent.width; spacing: Style.space(8)
    Rectangle {
      anchors.verticalCenter: parent.verticalCenter; width: Style.space(8); height: width; radius: width / 2
      color: root.privacy ? Color.accent : root.cameraLive ? Color.urgent : root.camera && root.camera.preview ? Color.foreground : Color.muted
    }
    Text {
      anchors.verticalCenter: parent.verticalCenter; width: parent.width - privacyButton.width - Style.space(24); elide: Text.ElideRight
      text: root.privacy ? "PRIVACY ON" : root.cameraLive ? "LIVE" + (root.appName ? " · " + root.appName.toUpperCase() : "") : root.camera && root.camera.preview ? "PREVIEW" : "IDLE"
      textFormat: Text.PlainText; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 10; font.bold: true
    }
    Rectangle {
      id: privacyButton
      width: Style.space(112); height: Style.space(28); radius: 0
      color: privacyArea.containsMouse ? root.panel.controlFaceRaised : root.panel.controlFace
      border.width: root.privacy ? 2 : 1; border.color: root.privacy ? Color.accent : root.panel.controlBorder
      Text { anchors.centerIn: parent; text: root.privacy ? "SHOW CAMERA" : "PRIVACY"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
      MouseArea { id: privacyArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.command(["privacy"]) }
    }
  }

  Column {
    width: parent.width; spacing: Style.space(6)
    Text { text: "PRESETS"; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
    Flow {
      visible: !root.naming; width: parent.width; spacing: Style.space(6)
      Repeater { model: root.presets
        Rectangle {
          required property var modelData
          width: Math.min(chipText.implicitWidth + Style.space(20), root.width); height: Style.space(28); radius: 0
          color: chipArea.containsMouse ? root.panel.controlFaceRaised : root.panel.controlFace
          border.width: root.isActive(modelData.name) ? 2 : 1; border.color: root.isActive(modelData.name) ? Color.accent : root.panel.controlBorder
          Text { id: chipText; anchors.centerIn: parent; width: Math.min(implicitWidth, parent.width - Style.space(12)); elide: Text.ElideRight; text: modelData.name; textFormat: Text.PlainText; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 10; font.bold: true }
          MouseArea { id: chipArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.command(["apply-preset", modelData.name]) }
        }
      }
      Rectangle {
        width: saveText.implicitWidth + Style.space(20); height: Style.space(28); radius: 0
        color: saveArea.containsMouse ? root.panel.controlFaceRaised : root.panel.controlFace; border.color: root.panel.controlBorder
        Text { id: saveText; anchors.centerIn: parent; text: root.activePreset ? "+ SAVE AS" : "+ SAVE"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
        MouseArea { id: saveArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { root.naming = true; nameField.forceActiveFocus() } }
      }
      // Removes the highlighted preset.
      Rectangle {
        visible: root.activePreset !== ""
        width: Style.space(28); height: Style.space(28); radius: 0
        color: deleteArea.containsMouse ? root.panel.controlFaceRaised : root.panel.controlFace; border.color: root.panel.controlBorder
        Text { anchors.centerIn: parent; text: "×"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 13 }
        MouseArea { id: deleteArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.command(["delete-preset", root.activePreset]) }
      }
    }
    Row {
      visible: root.naming; width: parent.width; spacing: Style.space(6)
      TextField {
        id: nameField
        width: parent.width - Style.space(102); height: Style.space(28); verticalPadding: Style.space(3)
        placeholderText: "Preset name"; maximumLength: 24; font.pixelSize: 10
        onAccepted: root.savePreset()
        Keys.onEscapePressed: root.stopNaming()
      }
      Rectangle {
        width: Style.space(56); height: Style.space(28); radius: 0; color: root.panel.controlFace; border.color: Color.accent
        Text { anchors.centerIn: parent; text: "SAVE"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.savePreset() }
      }
      Rectangle {
        width: Style.space(28); height: Style.space(28); radius: 0; color: root.panel.controlFace; border.color: root.panel.controlBorder
        Text { anchors.centerIn: parent; text: "×"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 13 }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.stopNaming() }
      }
    }
  }
}
