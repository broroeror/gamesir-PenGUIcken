import QtQuick
import QtQuick.Dialogs
import QtCore

// Backup / restore the whole controller (all 4 profiles + lighting) to/from a
// JSON file, with live progress. Drives bridge.exportBackup / importBackup.
Column {
    id: panel
    spacing: 12
    property string status: ""
    property bool statusOk: true
    property int progDone: 0
    property int progTotal: 0

    Connections {
        target: bridge
        function onBackupProgress(d, t) { panel.progDone = d; panel.progTotal = t }
        function onBackupStatus(ok, msg) {
            panel.status = msg; panel.statusOk = ok
            panel.progDone = 0; panel.progTotal = 0
        }
    }

    Text {
        width: parent.width; wrapMode: Text.WordWrap
        text: "Snapshot every profile + lighting to a file, or write a saved " +
              "snapshot back. Restoring overwrites the controller."
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    Row {
        spacing: 8
        PillButton {
            label: "Back up to file…"
            highlight: true
            opacity: bridge.backupBusy ? 0.5 : 1
            onClicked: if (!bridge.backupBusy) {
                // Pre-fill a dated filename so the user only has to confirm.
                saveDlg.selectedFile = saveDlg.currentFolder + "/" + bridge.defaultBackupName
                saveDlg.open()
            }
        }
        PillButton {
            label: "Restore from file…"
            opacity: bridge.backupBusy ? 0.5 : 1
            onClicked: if (!bridge.backupBusy) openDlg.open()
        }
    }

    // progress
    Rectangle {
        visible: bridge.backupBusy || panel.progTotal > 0
        width: parent.width; height: 8; radius: 4; color: Theme.track
        Rectangle {
            height: parent.height; radius: 4; color: Theme.accent
            width: panel.progTotal > 0 ? parent.width * panel.progDone / panel.progTotal : 0
        }
    }
    Text {
        visible: bridge.backupBusy
        text: "Working… " + panel.progDone + " / " + panel.progTotal + " blocks"
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }
    Text {
        visible: panel.status.length > 0 && !bridge.backupBusy
        width: parent.width; wrapMode: Text.WordWrap
        text: panel.status
        color: panel.statusOk ? Theme.ok : Theme.accent
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    FileDialog {
        id: saveDlg
        fileMode: FileDialog.SaveFile
        title: "Save controller backup"
        nameFilters: ["JSON files (*.json)"]
        defaultSuffix: "json"
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: bridge.exportBackup(selectedFile)
    }
    FileDialog {
        id: openDlg
        fileMode: FileDialog.OpenFile
        title: "Restore controller backup"
        nameFilters: ["JSON files (*.json)"]
        onAccepted: bridge.importBackup(selectedFile)
    }
}
