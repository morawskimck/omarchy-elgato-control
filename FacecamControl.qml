import QtQuick
import QtQuick.Controls as Controls
import qs.Commons
import qs.Ui

// One Facecam control, as the daemon describes it: a slider for a range, a
// switch for on/off, or segments for a menu. A manual value its automatic
// mode overrides is shown but cannot be changed.
Column {
  id: root
  property var control: ({})
  property var panel: null
  readonly property bool editable: !control.inactive && !control.readOnly
  // The value last sent, shown until the camera reports it or a moment
  // passes, so a released knob does not jump back while the helper runs.
  property int pendingValue: 0
  property bool pending: false
  readonly property int shownValue: pending ? pendingValue : (control.value || 0)
  onControlChanged: if (pending && control.value === pendingValue) pending = false
  function send(value) {
    pendingValue = value; pending = true; pendingTimer.restart()
    root.changed(control.name, value)
  }
  Timer { id: pendingTimer; interval: 2000; onTriggered: root.pending = false }
  // A logarithmic slider runs 0-1 and maps to the control's range.
  readonly property bool logarithmic: control.curve === "log" && control.min > 0
  signal changed(string name, int value)
  spacing: Style.space(5)

  function toSlider(value) {
    return logarithmic ? Math.log(value / control.min) / Math.log(control.max / control.min) : value
  }
  function fromSlider(position) {
    return Math.round(logarithmic ? control.min * Math.pow(control.max / control.min, position) : position)
  }
  function display(value) {
    return (Number(value) * (control.scale || 1)).toFixed(control.decimals || 0) + (control.unit || "")
  }

  Item {
    width: parent.width; height: Math.max(labelText.implicitHeight, control.kind === "toggle" ? toggle.height : 0)
    Text {
      id: labelText
      anchors.left: parent.left; anchors.right: valueText.left; anchors.verticalCenter: parent.verticalCenter
      text: String(root.control.label || "").toUpperCase() + (root.control.inactive ? " · AUTO" : ""); textFormat: Text.PlainText
      elide: Text.ElideRight; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true
    }
    Text {
      id: valueText
      visible: root.control.kind === "range"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
      text: root.display(slider.pressed ? root.fromSlider(slider.value) : root.shownValue)
      color: Color.foreground; font.family: Style.font.family; font.pixelSize: 10; font.bold: true
    }
    ToggleSwitch {
      id: toggle
      visible: root.control.kind === "toggle"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
      checked: root.shownValue === 1; interactive: root.editable; opacity: root.editable ? 1 : .45
      onToggled: root.send(checked ? 0 : 1)
    }
  }

  Controls.Slider {
    id: slider
    visible: root.control.kind === "range"; width: parent.width; height: Style.space(20)
    from: root.logarithmic ? 0 : root.control.min || 0; to: root.logarithmic ? 1 : root.control.max || 1
    stepSize: root.logarithmic ? 0 : root.control.step || 1
    snapMode: root.logarithmic ? Controls.Slider.NoSnap : Controls.Slider.SnapAlways; enabled: root.editable; opacity: root.editable ? 1 : .45
    // Follow the camera, but not under the pointer: a status refresh must not drag the knob away.
    Binding on value { when: !slider.pressed; value: root.toSlider(root.shownValue) }
    onMoved: root.send(root.fromSlider(value))
    background: Rectangle { x: slider.leftPadding; y: slider.topPadding + slider.availableHeight / 2 - height / 2; width: slider.availableWidth; height: Style.space(4); radius: 0; color: Qt.rgba(1,1,1,.12)
      Rectangle { width: slider.visualPosition * parent.width; height: parent.height; radius: 0; color: Color.accent }
    }
    handle: Rectangle { x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width); y: slider.topPadding + slider.availableHeight / 2 - height / 2; implicitWidth: Style.space(12); implicitHeight: Style.space(18); radius: 0; color: Color.foreground; border.color: root.panel ? root.panel.controlBorder : Color.muted }
  }

  Row {
    visible: root.control.kind === "choice"; width: parent.width; spacing: Style.space(5); opacity: root.editable ? 1 : .45
    Repeater { model: root.control.kind === "choice" ? root.control.menu : []
      Rectangle {
        required property var modelData
        readonly property bool selected: modelData.value === root.shownValue
        width: (parent.width - Style.space(5) * (root.control.menu.length - 1)) / root.control.menu.length; height: Style.space(28); radius: 0
        color: selected ? root.panel.controlFaceRaised : root.panel.controlFace
        border.width: selected ? 2 : 1; border.color: selected ? Color.accent : root.panel.controlBorder
        Text { anchors.centerIn: parent; text: String(modelData.label).toUpperCase(); textFormat: Text.PlainText; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
        MouseArea { anchors.fill: parent; enabled: root.editable; cursorShape: Qt.PointingHandCursor; onClicked: root.send(modelData.value) }
      }
    }
  }
}
