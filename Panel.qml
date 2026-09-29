import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.amitcpatel.elgato-control"
  ipcTarget: "io.github.amitcpatel.elgato-control"
  manageIpc: false
  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root
  property var status: ({ running: false, plus: null, deck: null, pedal: null, profile: "Omarchy Default", brightness: 55 })
  property var profile: ({ keys: [], dials: [], pedals: [] })
  property string error: ""
  readonly property bool connected: status.plus != null || status.deck != null || status.pedal != null
  readonly property bool hasPlus: status.plus != null
  // Either a Stream Deck + or a key-only panel (MK.2, XL, Original V2) drives the key grid.
  readonly property var deck: status.plus != null ? status.plus : status.deck
  readonly property bool hasDeck: deck != null
  readonly property bool hasDials: (profile.dials || []).length > 0 && hasPlus
  readonly property int deckColumns: hasDeck && deck.columns ? deck.columns : 4
  readonly property int deckKeys: hasDeck && deck.keys ? deck.keys : (profile.keys || []).length
  readonly property bool hasPedal: status.pedal != null
  // Page 1 is the profile's `keys` list; `pages` holds any further pages.
  property int selectedPage: 0
  readonly property int pageCount: 1 + (profile.pages || []).length
  readonly property int livePage: status.page || 0
  readonly property bool hasScreen: hasDeck && (deck.capabilities || []).indexOf("screen") >= 0
  onPageCountChanged: if (selectedPage >= pageCount) selectedPage = pageCount - 1
  readonly property bool hasWave: status.wave !== null && status.wave !== undefined
  readonly property bool hasLights: (status.lights || []).some(function(x) { return x.reachable })
  readonly property string helper: Qt.resolvedUrl("bin/elgato-control").toString().replace("file://", "")
  property var actionOptions: []
  property string selectedDevice: "streamdeck"
  property string selectedControl: "key"
  property int selectedIndex: 0
  property int selectedLightIndex: -1
  readonly property color controlFace: "#080808"
  readonly property color controlFaceRaised: "#111111"
  readonly property color controlBorder: Qt.rgba(1, 1, 1, 0.22)
  readonly property var deviceOptions: [
    hasDeck ? { value: "streamdeck", label: deck.label || "Stream Deck" } : null,
    hasPedal ? { value: "pedal", label: "Pedal" } : null,
    hasWave ? { value: "wave", label: "Wave:3" } : null,
    hasLights ? { value: "lights", label: "Key Lights" } : null
  ].filter(function(x) { return x !== null })

  function selectControl(type, index) { selectedControl = type; selectedIndex = index }
  function pageKeys(page) { return page === 0 ? (profile.keys || []) : (((profile.pages || [])[page - 1] || {}).keys || []) }
  function addPage() {
    if (pageProc.running) return
    pageProc.command = [root.helper, "add-page"]
    root.selectedPage = root.pageCount
    pageProc.running = true
  }
  function removePage() {
    if (pageProc.running || root.pageCount <= 1) return
    pageProc.command = [root.helper, "remove-page", String(root.selectedPage + 1)]
    root.selectedPage = Math.max(0, root.selectedPage - 1)
    pageProc.running = true
  }
  function actionName(value) {
    for (var i = 0; i < actionOptions.length; i++) if (actionOptions[i].value === value) return actionOptions[i].label.replace(/^(Function|Application|Key) · /, "")
    return value || "Unassigned"
  }
  function actionIcon(value) {
    for (var i = 0; i < actionOptions.length; i++) if (actionOptions[i].value === value) return actionOptions[i].icon || ""
    return ""
  }
  function saveAction(slot, action) {
    if (selectedDevice === "streamdeck" && selectedControl === "key") saveProc.command = [helper, "set-key", String(selectedIndex + 1), action, "--page", String(root.selectedPage + 1)]
    else if (selectedDevice === "streamdeck" && selectedControl === "dial") saveProc.command = [helper, "set-dial", String(selectedIndex + 1), slot, action]
    else if (selectedDevice === "pedal") saveProc.command = [helper, "set-pedal", String(selectedIndex + 1), action]
    else return
    saveProc.running = true
  }
  function waveAction(action) {
    waveProc.command = [root.helper, "wave", action]
    waveProc.running = true
  }
  function selectedLights() {
    var lights = root.status.lights || []
    return root.selectedLightIndex < 0 ? lights.filter(function(light) { return light.reachable }) : (lights[root.selectedLightIndex] ? [lights[root.selectedLightIndex]] : [])
  }
  function selectedLightName() {
    if (root.selectedLightIndex < 0) return "All Key Lights"
    return ((root.status.lights || [])[root.selectedLightIndex] || {}).name || "Key Light"
  }
  function selectedLightValue(field, fallback) {
    var lights = selectedLights().filter(function(light) { return light.reachable && light[field] !== undefined })
    if (lights.length === 0) return fallback
    var total = 0
    for (var i = 0; i < lights.length; i++) total += Number(lights[i][field])
    return Math.round(total / lights.length)
  }
  function selectedLightReachable() { return selectedLights().some(function(light) { return light.reachable }) }
  function selectedLightOn() { return selectedLights().some(function(light) { return light.reachable && light.on }) }
  function lightAction(action, value) {
    if (lightProc.running) return
    lightProc.command = [root.helper, "lights", action, "--target", root.selectedLightIndex < 0 ? "all" : String(root.selectedLightIndex)]
    if (value !== undefined) lightProc.command = lightProc.command.concat(["--value", String(Math.round(value))])
    lightProc.running = true
  }

  // The catalog enumerates installed .desktop files, so it goes stale as soon
  // as an application is added or removed. refresh() runs on a timer and must
  // not rescan that often, so rebuild it once per open instead of only when
  // it has never been loaded.
  function open() {
    root.controller.show()
    if (!catalogProc.running) catalogProc.running = true
    refresh()
  }
  function close() { root.controller.hide() }
  function toggle() { if (root.opened) close(); else open() }
  function refresh() {
    if (!statusProc.running) statusProc.running = true
    if (!profileProc.running) profileProc.running = true
    if (root.actionOptions.length === 0 && !catalogProc.running) catalogProc.running = true
  }
  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function") return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  Process {
    id: statusProc
    command: [root.helper, "status", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try { root.status = JSON.parse(text); root.error = "" }
        catch (e) { root.error = "Could not read Stream Deck status" }
      }
    }
  }
  Process {
    id: catalogProc
    command: [root.helper, "catalog"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: { try { root.actionOptions = JSON.parse(text) } catch (e) { root.error = "Could not load action catalog" } }
    }
  }
  Process {
    id: profileProc
    command: [root.helper, "profile"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: { try { root.profile = JSON.parse(text) } catch (e) {} }
    }
  }
  Process { id: saveProc; onExited: function() { root.refresh() } }
  Process { id: pageProc; onExited: function() { root.refresh() } }
  Process { id: waveProc; onExited: function() { root.refresh() } }
  Process {
    id: lightProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var next = Object.assign({}, root.status)
          next.lights = JSON.parse(text)
          root.status = next
          root.error = ""
        } catch (e) { root.refresh() }
      }
    }
    onExited: function(code) { if (code !== 0) root.error = "Key Light control failed"; root.refresh() }
  }
  Timer { interval: 1500; repeat: true; running: root.opened; triggeredOnStart: true; onTriggered: root.refresh() }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(700))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: content
        width: parent.width
        spacing: Style.space(10)

        Row {
          width: parent.width
          spacing: Style.space(10)
          Image { width: Style.space(28); height: width; source: Qt.resolvedUrl("assets/elgato.svg"); fillMode: Image.PreserveAspectFit }
          Column {
            width: parent.width - Style.space(120)
            Text { text: "Elgato Control"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 16; font.bold: true }
            Text { text: root.status.profile || "Omarchy Default"; textFormat: Text.PlainText; color: Color.muted; font.family: Style.font.family; font.pixelSize: 11 }
          }
          Text { text: root.connected ? "Connected" : "Disconnected"; color: root.connected ? Color.accent : Color.muted; font.family: Style.font.family; font.pixelSize: 11 }
        }

        Rectangle { width: parent.width; height: 1; color: Qt.rgba(1, 1, 1, 0.2) }

        ButtonGroup {
          width: parent.width
          options: root.deviceOptions
          value: root.selectedDevice
          onChanged: function(value) { root.selectedDevice = value; root.selectedIndex = 0; root.selectedLightIndex = -1; root.selectedControl = value === "streamdeck" ? "key" : value }
        }

        Row {
          width: parent.width; spacing: Style.space(14)

          Rectangle {
            width: parent.width * 0.61; radius: 0
            height: Math.max(Style.space(310), root.selectedDevice === "streamdeck"
                             ? deckColumn.implicitHeight + Style.space(28) : 0)
            color: Qt.rgba(0, 0, 0, 0.28); border.color: Qt.rgba(1, 1, 1, 0.14)

            Column {
              id: deckColumn
              visible: root.selectedDevice === "streamdeck"; anchors.centerIn: parent; width: parent.width - Style.space(28); spacing: Style.space(10)
              Text { anchors.horizontalCenter: parent.horizontalCenter; text: (root.hasDeck && root.deck.label ? root.deck.label : "Stream Deck").toUpperCase(); color: Color.muted; font.family: Style.font.family; font.pixelSize: 10; font.bold: true }
              Row {
                anchors.horizontalCenter: parent.horizontalCenter; spacing: Style.space(6)
                Text { anchors.verticalCenter: parent.verticalCenter; text: "PAGE"; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
                Repeater { model: root.pageCount
                  Rectangle {
                    required property int index
                    width: Style.space(26); height: Style.space(22); radius: 0
                    color: root.selectedPage === index ? root.controlFaceRaised : root.controlFace
                    border.width: root.selectedPage === index ? 2 : 1
                    border.color: root.selectedPage === index ? Color.accent : root.controlBorder
                    Text { anchors.centerIn: parent; text: index + 1; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 10; font.bold: true }
                    // Marks the page the panel is showing right now.
                    Rectangle { visible: root.livePage === index && root.pageCount > 1; anchors.top: parent.top; anchors.right: parent.right; anchors.margins: Style.space(3); width: Style.space(4); height: width; radius: width / 2; color: Color.accent }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.selectedPage = index }
                  }
                }
                Rectangle {
                  width: Style.space(26); height: Style.space(22); radius: 0; color: addPageArea.containsMouse ? root.controlFaceRaised : root.controlFace; border.color: root.controlBorder
                  Text { anchors.centerIn: parent; text: "+"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 13 }
                  MouseArea { id: addPageArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.addPage() }
                }
                Rectangle {
                  visible: root.pageCount > 1
                  width: Style.space(26); height: Style.space(22); radius: 0; color: removePageArea.containsMouse ? root.controlFaceRaised : root.controlFace; border.color: root.controlBorder
                  Text { anchors.centerIn: parent; text: "×"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 13 }
                  MouseArea { id: removePageArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.removePage() }
                }
              }
              Grid {
                id: keyGrid
                width: parent.width; columns: root.deckColumns; columnSpacing: Style.space(8); rowSpacing: Style.space(8)
                readonly property real cell: (width - Style.space(8) * (root.deckColumns - 1)) / root.deckColumns
                Repeater {
                  model: root.pageKeys(root.selectedPage).slice(0, root.deckKeys)
                  Rectangle {
                    width: keyGrid.cell; height: width; radius: 0
                    clip: true
                    color: root.selectedControl === "key" && root.selectedIndex === index ? root.controlFaceRaised : root.controlFace
                    border.width: root.selectedControl === "key" && root.selectedIndex === index ? 2 : 1
                    border.color: root.selectedControl === "key" && root.selectedIndex === index ? Color.accent : root.controlBorder
                    Column { anchors.centerIn: parent; width: parent.width - Style.space(10); spacing: Style.space(3)
                      Text { anchors.horizontalCenter: parent.horizontalCenter; text: index + 1; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9 }
                      Image { anchors.horizontalCenter: parent.horizontalCenter; width: Math.min(Style.space(30), keyGrid.cell * 0.42); height: width; source: root.actionIcon(modelData.action); visible: source.toString() !== ""; fillMode: Image.PreserveAspectFit; smooth: true }
                      Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: root.actionName(modelData.action); textFormat: Text.PlainText; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 9 }
                    }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.selectControl("key", index) }
                  }
                }
              }
              Row {
                visible: root.hasScreen
                width: parent.width; spacing: Style.space(8)
                Repeater { model: 3
                  Rectangle {
                    required property int index
                    width: index === 1 ? parent.width - 2 * keyGrid.cell - Style.space(16) : keyGrid.cell
                    height: Style.space(34); radius: 0
                    color: index === 1 ? "#000000" : root.controlFace; border.color: root.controlBorder
                    Text {
                      anchors.centerIn: parent; color: index === 1 ? Color.foreground : Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true
                      text: index === 1 ? "CLOCK · STATUS" + (root.pageCount > 1 ? " · PAGE " + (root.livePage + 1) + "/" + root.pageCount : "")
                                        : (index === 0 ? "◀ PAGE" : "PAGE ▶")
                    }
                  }
                }
              }
              Column {
                visible: root.hasDials
                width: parent.width; spacing: Style.space(2)
                Rectangle {
                  width: parent.width; height: Style.space(42); radius: 0; color: Qt.rgba(0, 0, 0, .5); border.color: Qt.rgba(1, 1, 1, .15)
                  Row { anchors.fill: parent
                    Repeater { model: root.profile.dials || []
                      Text { width: parent.width / 4; anchors.verticalCenter: parent.verticalCenter; horizontalAlignment: Text.AlignHCenter; text: modelData.label; textFormat: Text.PlainText; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; elide: Text.ElideRight }
                    }
                  }
                }
                Row {
                  width: parent.width; spacing: 0
                  Repeater { model: root.profile.dials || []
                    Item {
                      width: parent.width / 4; height: Style.space(38)
                      Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top
                        width: Style.space(34); height: width; radius: width / 2
                        color: root.selectedControl === "dial" && root.selectedIndex === index ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, .25) : Qt.rgba(1, 1, 1, .06)
                        border.color: root.selectedControl === "dial" && root.selectedIndex === index ? Color.accent : Qt.rgba(1, 1, 1, .22)
                        Text { anchors.centerIn: parent; text: index + 1; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 10 }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.selectControl("dial", index) }
                      }
                    }
                  }
                }
              }
            }

            Row {
              visible: root.selectedDevice === "pedal"; anchors.centerIn: parent; width: parent.width - Style.space(36); spacing: Style.space(12)
              Repeater { model: root.profile.pedals || []
                Rectangle {
                  width: (parent.width - Style.space(24)) / 3; height: Style.space(150); radius: 0
                  color: root.selectedIndex === index ? root.controlFaceRaised : root.controlFace
                  border.width: root.selectedIndex === index ? 2 : 1
                  border.color: root.selectedIndex === index ? Color.accent : root.controlBorder
                  Column { anchors.centerIn: parent; width: parent.width - Style.space(12); spacing: Style.space(8)
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: ["LEFT", "MIDDLE", "RIGHT"][index]; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
                    Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; text: root.actionName(modelData.action); textFormat: Text.PlainText; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 11 }
                  }
                  MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { root.selectedControl = "pedal"; root.selectedIndex = index } }
                }
              }
            }

            Column {
              visible: root.selectedDevice === "wave"; anchors.centerIn: parent; width: parent.width - Style.space(40); spacing: Style.space(12)
              Text { anchors.horizontalCenter: parent.horizontalCenter; text: "󰍬"; color: root.status.wave && root.status.wave.muted ? Color.urgent : Color.accent; font.family: Style.font.family; font.pixelSize: 54 }
              Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.status.wave ? root.status.wave.product : "Wave microphone"; textFormat: Text.PlainText; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 15; font.bold: true }
              Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.status.wave && root.status.wave.muted ? "MUTED" : "LIVE"; color: root.status.wave && root.status.wave.muted ? Color.urgent : Color.accent; font.family: Style.font.family; font.pixelSize: 10; font.bold: true }
              Rectangle { width: parent.width; height: Style.space(8); radius: 0; color: Qt.rgba(1, 1, 1, .08)
                Rectangle { width: parent.width * ((root.status.wave && root.status.wave.gainPercent || 0) / 100); height: parent.height; radius: 0; color: Color.accent }
              }
              Row { width: parent.width
                Text { width: parent.width / 2; text: "MIC GAIN  " + (root.status.wave && root.status.wave.gainDb !== null ? root.status.wave.gainDb + " dB" : "--"); color: Color.foreground; font.family: Style.font.family; font.pixelSize: 11; font.bold: true }
                Text { width: parent.width / 2; horizontalAlignment: Text.AlignRight; text: "HEADPHONES  " + (root.status.wave && root.status.wave.headphonePercent !== null ? root.status.wave.headphonePercent + "%" : "--"); color: Color.foreground; font.family: Style.font.family; font.pixelSize: 11; font.bold: true }
              }
            }

            Column {
              visible: root.selectedDevice === "lights"; anchors.centerIn: parent; width: parent.width - Style.space(28); spacing: Style.space(12)
              Text { text: "SELECT LIGHT"; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
              Row {
                width: parent.width; spacing: Style.space(8)
                Rectangle {
                  width: (parent.width - Style.space(16)) / 3; height: Style.space(140); radius: 0; color: root.controlFace
                  border.width: root.selectedLightIndex === -1 ? 2 : 1; border.color: root.selectedLightIndex === -1 ? Color.accent : root.controlBorder
                  Column { anchors.centerIn: parent; spacing: Style.space(7)
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "󰛨"; color: root.selectedLightOn() ? "#f0b632" : Color.muted; font.family: Style.font.family; font.pixelSize: 30 }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "ALL LIGHTS"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 10; font.bold: true }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.selectedLightReachable() ? root.selectedLightValue("brightness", 0) + "%" : "Unavailable"; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9 }
                  }
                  MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.selectedLightIndex = -1 }
                }
                Repeater { model: root.status.lights || []
                  Rectangle {
                    required property var modelData; required property int index
                    width: (parent.width - Style.space(16)) / 3; height: Style.space(140); radius: 0; color: root.controlFace
                    border.width: root.selectedLightIndex === index ? 2 : 1; border.color: root.selectedLightIndex === index ? Color.accent : root.controlBorder
                    Column { anchors.centerIn: parent; width: parent.width - Style.space(8); spacing: Style.space(7)
                      Text { anchors.horizontalCenter: parent.horizontalCenter; text: "󰛨"; color: modelData.on ? "#f0b632" : Color.muted; font.family: Style.font.family; font.pixelSize: 30 }
                      Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: modelData.name; textFormat: Text.PlainText; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 10; font.bold: true }
                      Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.reachable ? modelData.brightness + "% · " + Math.round(1000000 / modelData.temperature) + "K" : "Unavailable"; color: modelData.reachable ? Color.muted : Color.urgent; font.family: Style.font.family; font.pixelSize: 9 }
                    }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.selectedLightIndex = index }
                  }
                }
              }
            }
          }

          Column {
            width: parent.width * 0.39 - Style.space(14); spacing: Style.space(10)
            Text { text: "ACTION INSPECTOR"; color: Color.muted; font.family: Style.font.family; font.pixelSize: 10; font.bold: true }
            Text {
              text: root.selectedDevice === "streamdeck" ? (root.selectedControl === "key" ? "Key " + (root.selectedIndex + 1) + (root.pageCount > 1 ? " · Page " + (root.selectedPage + 1) : "") : "Dial " + (root.selectedIndex + 1)) : root.selectedDevice === "pedal" ? ["Left pedal", "Middle pedal", "Right pedal"][root.selectedIndex] : root.selectedDevice === "wave" ? "Wave:3" : root.selectedLightName(); textFormat: Text.PlainText
              color: Color.foreground; font.family: Style.font.family; font.pixelSize: 15; font.bold: true
            }
            Text { visible: root.selectedDevice === "streamdeck" || root.selectedDevice === "pedal"; width: parent.width; wrapMode: Text.WordWrap; text: "Choose an application, system function, or key. Changes apply immediately."; color: Color.muted; font.family: Style.font.family; font.pixelSize: 10 }
            SearchableDropdown {
              visible: (root.selectedDevice === "streamdeck" && root.selectedControl === "key") || root.selectedDevice === "pedal"
              width: parent.width; label: "On press"; options: root.actionOptions
              value: root.selectedDevice === "pedal" ? ((root.profile.pedals[root.selectedIndex] || {}).action || "") : ((root.pageKeys(root.selectedPage)[root.selectedIndex] || {}).action || "")
              onChanged: function(action) { root.saveAction("action", action) }
            }
            Column {
              visible: root.selectedDevice === "streamdeck" && root.selectedControl === "dial" && root.hasDials; width: parent.width; spacing: Style.space(10)
              Repeater { model: [{slot:"left",label:"Turn left"},{slot:"press",label:"Press"},{slot:"right",label:"Turn right"}]
                SearchableDropdown { required property var modelData; width: parent.width; label: modelData.label; options: root.actionOptions; value: (root.profile.dials[root.selectedIndex] || {})[modelData.slot] || ""; onChanged: function(action) { root.saveAction(modelData.slot, action) } }
              }
            }
            Column {
              visible: root.selectedDevice === "wave"; width: parent.width; spacing: Style.space(10)
              Text { text: "MICROPHONE GAIN"; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
              Row { width: parent.width; spacing: Style.space(6)
                Rectangle { width: Style.space(42); height: Style.space(34); radius: 0; color: gainDown.containsMouse ? root.controlFaceRaised : root.controlFace; border.color: root.controlBorder
                  Text { anchors.centerIn: parent; text: "−"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 18 }
                  MouseArea { id: gainDown; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.waveAction("gain-down") }
                }
                Rectangle { width: parent.width - Style.space(96); height: Style.space(34); radius: 0; color: Qt.rgba(1,1,1,.035); border.color: Qt.rgba(1,1,1,.15)
                  Text { anchors.centerIn: parent; text: root.status.wave && root.status.wave.gainDb !== null ? root.status.wave.gainDb + " dB" : "--"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 12; font.bold: true }
                }
                Rectangle { width: Style.space(42); height: Style.space(34); radius: 0; color: gainUp.containsMouse ? root.controlFaceRaised : root.controlFace; border.color: root.controlBorder
                  Text { anchors.centerIn: parent; text: "+"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 18 }
                  MouseArea { id: gainUp; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.waveAction("gain-up") }
                }
              }
              Rectangle { width: parent.width; height: Style.space(36); radius: 0; color: root.controlFace; border.color: root.status.wave && root.status.wave.muted ? Color.urgent : root.controlBorder
                Text { anchors.centerIn: parent; text: root.status.wave && root.status.wave.muted ? "UNMUTE MICROPHONE" : "MUTE MICROPHONE"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 10; font.bold: true }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.waveAction("mute") }
              }
              Text { text: "HEADPHONES"; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
              Row { width: parent.width; spacing: Style.space(6)
                Repeater { model: [{label:"−",action:"headphone-down"},{label:(root.status.wave ? root.status.wave.headphonePercent : "--") + "%",action:"headphone-mute"},{label:"+",action:"headphone-up"}]
                  Rectangle { required property var modelData; width: (parent.width - Style.space(12)) / 3; height: Style.space(34); radius: 0; color: root.controlFace; border.color: root.controlBorder
                    Text { anchors.centerIn: parent; text: modelData.label; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 11; font.bold: true }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.waveAction(modelData.action) }
                  }
                }
              }
              Text { text: "GAIN PRESETS"; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
              Row { width: parent.width; spacing: Style.space(5)
                Repeater { model: [{label:"QUIET",action:"preset-quiet"},{label:"NORMAL",action:"preset-normal"},{label:"LOUD",action:"preset-loud"}]
                  Rectangle { required property var modelData; width: (parent.width - Style.space(10)) / 3; height: Style.space(32); radius: 0; color: root.controlFace; border.color: root.controlBorder
                    Text { anchors.centerIn: parent; text: modelData.label; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.waveAction(modelData.action) }
                  }
                }
              }
              Rectangle { width: parent.width; height: Style.space(34); radius: 0; color: Qt.rgba(Color.accent.r,Color.accent.g,Color.accent.b,.12); border.color: Color.accent
                Text { anchors.centerIn: parent; text: "USE AS DEFAULT MICROPHONE"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.waveAction("default") }
              }
            }
            Column {
              visible: root.selectedDevice === "lights"; width: parent.width; spacing: Style.space(9)
              Text { text: root.selectedLightReachable() ? (root.selectedLightOn() ? "ON · REACHABLE" : "OFF · REACHABLE") : "UNAVAILABLE"; color: root.selectedLightReachable() ? (root.selectedLightOn() ? "#f0b632" : Color.muted) : Color.urgent; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
              Text { text: "POWER"; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
              Row { width: parent.width; spacing: Style.space(6)
                Repeater { model: [{label:"ON",action:"on"},{label:"OFF",action:"off"}]
                  Rectangle { required property var modelData; width: (parent.width - Style.space(6)) / 2; height: Style.space(32); radius: 0; color: root.controlFace; border.color: root.controlBorder; opacity: root.selectedLightReachable() ? 1 : .45
                    Text { anchors.centerIn: parent; text: modelData.label; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
                    MouseArea { anchors.fill: parent; enabled: root.selectedLightReachable(); cursorShape: Qt.PointingHandCursor; onClicked: root.lightAction(modelData.action) }
                  }
                }
              }
              Text { text: "BRIGHTNESS  " + root.selectedLightValue("brightness", 0) + "%"; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
              Controls.Slider {
                id: lightBrightness; width: parent.width; from: 1; to: 100; stepSize: 1; value: root.selectedLightValue("brightness", 40); enabled: root.selectedLightReachable() && !lightProc.running
                onPressedChanged: if (!pressed) root.lightAction("brightness", value)
                background: Rectangle { x: lightBrightness.leftPadding; y: lightBrightness.topPadding + lightBrightness.availableHeight / 2 - height / 2; width: lightBrightness.availableWidth; height: Style.space(4); radius: 0; color: Qt.rgba(1,1,1,.12)
                  Rectangle { width: lightBrightness.visualPosition * parent.width; height: parent.height; radius: 0; color: Color.accent }
                }
                handle: Rectangle { x: lightBrightness.leftPadding + lightBrightness.visualPosition * (lightBrightness.availableWidth - width); y: lightBrightness.topPadding + lightBrightness.availableHeight / 2 - height / 2; implicitWidth: Style.space(12); implicitHeight: Style.space(18); radius: 0; color: Color.foreground; border.color: root.controlBorder }
              }
              Text { text: "TEMPERATURE  " + Math.round(1000000 / root.selectedLightValue("temperature", 200)) + "K"; color: Color.muted; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
              Controls.Slider {
                id: lightTemperature; width: parent.width; from: 2900; to: 7000; stepSize: 100; value: Math.round(1000000 / root.selectedLightValue("temperature", 200)); enabled: root.selectedLightReachable() && !lightProc.running
                onPressedChanged: if (!pressed) root.lightAction("temperature", value)
                background: Rectangle { x: lightTemperature.leftPadding; y: lightTemperature.topPadding + lightTemperature.availableHeight / 2 - height / 2; width: lightTemperature.availableWidth; height: Style.space(4); radius: 0; color: Qt.rgba(1,1,1,.12)
                  Rectangle { width: lightTemperature.visualPosition * parent.width; height: parent.height; radius: 0; color: "#f0b632" }
                }
                handle: Rectangle { x: lightTemperature.leftPadding + lightTemperature.visualPosition * (lightTemperature.availableWidth - width); y: lightTemperature.topPadding + lightTemperature.availableHeight / 2 - height / 2; implicitWidth: Style.space(12); implicitHeight: Style.space(18); radius: 0; color: Color.foreground; border.color: root.controlBorder }
              }
              Rectangle { width: parent.width; height: Style.space(32); radius: 0; color: root.controlFace; border.color: root.controlBorder
                Text { anchors.centerIn: parent; text: lightProc.running ? "UPDATING…" : "REFRESH LIGHTS"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: 9; font.bold: true }
                MouseArea { anchors.fill: parent; enabled: !lightProc.running; cursorShape: Qt.PointingHandCursor; onClicked: root.lightAction("refresh") }
              }
            }
          }
        }

        Text { visible: !!root.status.lastAction; text: "Last action: " + (root.status.lastAction || "") + " · " + (root.status.lastEvent || ""); textFormat: Text.PlainText; color: Color.muted; font.family: Style.font.family; font.pixelSize: 10 }
        Text { visible: root.error !== "" || !!root.status.error; text: root.error || root.status.error || ""; textFormat: Text.PlainText; color: Color.urgent; font.family: Style.font.family; font.pixelSize: 11 }

      }
    }
  }
}
