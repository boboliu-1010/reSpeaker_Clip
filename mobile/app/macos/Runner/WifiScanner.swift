import Cocoa
import CoreLocation
import CoreWLAN
import FlutterMacOS

/// Explicitly requested scans only. Never reads Keychain passwords or BSSIDs.
final class WifiScanner: NSObject, CLLocationManagerDelegate {
  private let location = CLLocationManager()
  private var channel: FlutterMethodChannel?
  private var pending: FlutterResult?
  private var deadline: DispatchWorkItem?
  private var scanning = false

  func register(with messenger: FlutterBinaryMessenger) {
    location.delegate = self
    let channel = FlutterMethodChannel(name: "boa_voice/wifi", binaryMessenger: messenger)
    self.channel = channel
    channel.setMethodCallHandler { [weak self] call, result in
      guard call.method == "scan" else { result(FlutterMethodNotImplemented); return }
      self?.request(result)
    }
  }

  private func request(_ result: @escaping FlutterResult) {
    guard pending == nil && !scanning else { fail(result, "busy"); return }
    guard CLLocationManager.locationServicesEnabled() else { fail(result, "location_disabled"); return }
    switch location.authorizationStatus {
    case .authorizedAlways, .authorizedWhenInUse:
      scan(result)
    case .notDetermined:
      pending = result
      let timeout = DispatchWorkItem { [weak self] in
        guard let self = self, let callback = self.pending else { return }
        self.pending = nil
        self.fail(callback, "permission_pending")
      }
      deadline = timeout
      DispatchQueue.main.asyncAfter(deadline: .now() + 30, execute: timeout)
      NSApp.activate(ignoringOtherApps: true)
      location.requestWhenInUseAuthorization()
    default:
      fail(result, "permission_denied")
    }
  }

  func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
    guard manager.authorizationStatus != .notDetermined, let callback = pending else { return }
    pending = nil
    deadline?.cancel(); deadline = nil
    request(callback)
  }

  private func fail(_ result: FlutterResult, _ code: String) {
    result(FlutterError(code: code, message: code, details: nil))
  }

  private func scan(_ result: @escaping FlutterResult) {
    scanning = true
    DispatchQueue.global(qos: .userInitiated).async { [weak self] in
      guard let self = self else { return }
      var response: [String: Any]?
      var failure: String?
      do {
        guard let iface = CWWiFiClient.shared().interface(), iface.powerOn() else {
          DispatchQueue.main.async { self.scanning = false; self.fail(result, "wifi_off") }; return
        }
        let networks = try iface.scanForNetworks(withSSID: nil)
        var rows = [[String: Any]]()
        for network in networks.sorted(by: { $0.rssiValue > $1.rssiValue }).prefix(128) {
          guard let ssid = network.ssid, !ssid.isEmpty else { continue }
          let band: String
          switch network.wlanChannel?.channelBand {
          case .band2GHz: band = "2.4"
          case .band5GHz: band = "5"
          case .band6GHz: band = "6"
          default: band = "unknown"
          }
          let security: String
          if network.supportsSecurity(.wpa2Personal) || network.supportsSecurity(.wpaPersonalMixed) {
            security = "wpa2"
          } else if network.supportsSecurity(.wpa3Personal) {
            security = "wpa3"
          } else if network.supportsSecurity(.none) {
            security = "open"
          } else {
            security = "unsupported"
          }
          rows.append(["ssid": ssid, "rssi": network.rssiValue,
                       "channel": network.wlanChannel?.channelNumber ?? 0,
                       "band": band, "security": security])
        }
        if !networks.isEmpty && rows.isEmpty { failure = "ssid_unavailable" }
        else { response = ["source": "macos", "current_ssid": iface.ssid() as Any? ?? NSNull(), "networks": rows] }
      } catch { failure = "scan_failed" }
      DispatchQueue.main.async {
        self.scanning = false
        if let code = failure { self.fail(result, code) }
        else { result(response) }
      }
    }
  }
}
