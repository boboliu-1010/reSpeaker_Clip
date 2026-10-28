import Cocoa
import FlutterMacOS

class MainFlutterWindow: NSWindow {
  private let wifiScanner = WifiScanner()
  override func awakeFromNib() {
    let flutterViewController = FlutterViewController()
    let windowFrame = self.frame
    self.contentViewController = flutterViewController
    self.setFrame(NSRect(x: windowFrame.origin.x, y: windowFrame.origin.y, width: 1100, height: 760), display: true)
    self.minSize = NSSize(width: 900, height: 640)
    self.center()

    RegisterGeneratedPlugins(registry: flutterViewController)
    wifiScanner.register(with: flutterViewController.engine.binaryMessenger)

    super.awakeFromNib()
  }
}
