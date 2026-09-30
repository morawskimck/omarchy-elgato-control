import QtQuick
import qs.Commons
import qs.Ui

// The Facecam page's inspector: a tab per group of controls, then a reset.
Column {
  id: root
  property var camera: null
  property var panel: null
  property string group: "exposure"
  readonly property var groups: camera && camera.groups ? camera.groups : []
  readonly property var current: {
    for (var i = 0; i < groups.length; i++) if (groups[i].id === group) return groups[i]
    return groups.length ? groups[0] : null
  }
  signal setControl(string name, int value)
  // Arguments for `elgato-control facecam`.
  signal command(var arguments)
  spacing: Style.space(10)

  Row {
    width: parent.width; spacing: Style.space(4)
    Repeater { model: root.groups
      Rectangle {
        required property var modelData
        readonly property bool selected: root.current !== null && root.current.id === modelData.id
        width: (parent.width - Style.space(4) * (root.groups.length - 1)) / root.groups.length; height: Style.space(26); radius: 0
        color: selected ? root.panel.controlFaceRaised : root.panel.controlFace
        border.width: selected ? 2 : 1; border.color: selected ? Color.accent : root.panel.controlBorder
        Text { anchors.centerIn: parent; width: parent.width - Style.space(4); horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: String(modelData.label).toUpperCase(); textFormat: Text.PlainText; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.group = modelData.id }
      }
    }
  }

  Repeater { model: root.current ? root.current.controls : []
    FacecamControl {
      required property var modelData
      width: root.width; panel: root.panel
      control: root.camera && root.camera.controls[modelData] ? root.camera.controls[modelData] : ({})
      onChanged: function(name, value) { root.setControl(name, value) }
    }
  }

  Text {
    visible: root.groups.length === 0; width: parent.width; wrapMode: Text.WordWrap
    text: root.camera && root.camera.error ? root.camera.error : "Reading the camera…"; textFormat: Text.PlainText
    color: Color.muted; font.family: Style.font.family; font.pixelSize: 10
  }

  Rectangle {
    visible: root.groups.length > 0
    width: parent.width; height: Style.space(32); radius: 0
    color: resetArea.containsMouse ? root.panel.controlFaceRaised : root.panel.controlFace; border.color: root.panel.controlBorder
    Text { anchors.centerIn: parent; text: "RESET TO CAMERA DEFAULTS"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
    MouseArea { id: resetArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.command(["reset"]) }
  }
}
