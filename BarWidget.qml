import QtQuick
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.amitcpatel.elgato-control"

  function injectPanel() {
    if (!panelLoader.item) return
    panelLoader.item.bar = root.bar
    panelLoader.item.anchorItem = button
    panelLoader.item.hostWidget = root
  }
  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function closeForPopoutSwitch() { close() }
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool connected: panelLoader.item ? panelLoader.item.connected === true : false
  // Another app streams from the Facecam: a call is seeing you.
  readonly property bool cameraLive: panelLoader.item ? panelLoader.item.facecamLive === true : false
  readonly property bool cameraPrivate: cameraLive && panelLoader.item.facecam.privacy === true
  readonly property bool popoutSwitchClosing: false
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  onBarChanged: injectPanel()


  Loader {
    id: panelLoader
    active: true
    visible: false
    source: Qt.resolvedUrl("Panel.qml")
    onLoaded: root.injectPanel()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    dimmed: !root.connected
    tooltipText: root.cameraLive ? "Elgato Control · Camera live" + (root.cameraPrivate ? " (privacy on)" : "")
                 : root.connected ? "Elgato Control · Connected" : "Elgato Control · Disconnected"
    iconComponent: Component {
      Item {
        anchors.fill: parent
        Image {
          id: mark
          anchors.centerIn: parent
          width: Math.min(parent.width, parent.height) * 0.72
          height: width
          source: Qt.resolvedUrl("assets/elgato.svg")
          fillMode: Image.PreserveAspectFit
          smooth: true
        }
        Rectangle {
          visible: root.cameraLive
          width: mark.width * 0.36; height: width; radius: width / 2
          anchors.right: mark.right; anchors.top: mark.top; anchors.margins: -width * 0.15
          color: root.cameraPrivate ? Color.accent : Color.urgent
        }
      }
    }
    onPressed: function(mouseButton) { if (panelLoader.item) panelLoader.item.toggle() }
  }
}
