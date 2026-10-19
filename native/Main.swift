import AppKit
import WebKit
import Foundation

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var attempts = 0
    var port = Int.random(in: 21000...49000)
    let token = UUID().uuidString + UUID().uuidString
    var loading: NSTextField!
    func applicationDidFinishLaunching(_ notification: Notification) {
        let appMenu = NSMenu()
        let item = NSMenuItem()
        let submenu = NSMenu()
        submenu.addItem(withTitle: "About Local Explainer", action: #selector(about), keyEquivalent: "")
        submenu.addItem(NSMenuItem.separator())
        submenu.addItem(withTitle: "Quit Local Explainer", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = submenu
        appMenu.addItem(item)
        let editItem = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit; appMenu.addItem(editItem)
        NSApp.mainMenu = appMenu
        window = NSWindow(contentRect: NSRect(x:0,y:0,width:1340,height:900),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
        window.title = "Local Explainer"
        window.minSize = NSSize(width:850,height:660)
        window.center()
        window.backgroundColor = NSColor(calibratedRed:0.96,green:0.97,blue:0.95,alpha:1)
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.mediaTypesRequiringUserActionForPlayback = []
        web = WKWebView(frame:window.contentView!.bounds,configuration:config)
        web.autoresizingMask = [.width,.height]; web.uiDelegate=self; web.navigationDelegate=self
        window.contentView!.addSubview(web)
        loading=NSTextField(labelWithString:"Opening your local studio…")
        loading.font=NSFont.systemFont(ofSize:17,weight:.medium)
        loading.alignment = .center
        loading.frame=NSRect(x:0,y:window.contentView!.bounds.height/2,width:window.contentView!.bounds.width,height:40)
        loading.autoresizingMask=[.width,.minYMargin,.maxYMargin]
        window.contentView!.addSubview(loading)
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true)
        startServer()
    }
    func startServer() {
        let process=Process()
        guard let resources=Bundle.main.resourceURL else { fail("Application resources are missing."); return }
        process.executableURL=resources.appendingPathComponent("server/ExplainerServer")
        process.arguments=["--port",String(port)]
        var environment=ProcessInfo.processInfo.environment
        environment["EXPLAINER_TOKEN"]=token
        environment["EXPLAINER_PARENT_PID"]=String(ProcessInfo.processInfo.processIdentifier)
        environment["PATH"]="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        environment["EXPLAINER_BUNDLED_TOOLS"]=resources.appendingPathComponent("tools").path
        process.environment=environment
        let data=FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("Local Explainer")
        try? FileManager.default.createDirectory(at:data,withIntermediateDirectories:true)
        let logs=data.appendingPathComponent("launcher.log")
        FileManager.default.createFile(atPath:logs.path,contents:nil)
        if let handle=try? FileHandle(forWritingTo:logs) { process.standardOutput=handle; process.standardError=handle }
        do {try process.run(); server=process; poll()} catch {fail("Could not start the local service. Rebuild the app or check the launcher log in Application Support/Local Explainer.")}
    }
    func poll() {
        attempts += 1
        guard attempts<120 else { fail("The local service did not start. Check ~/Library/Application Support/Local Explainer/launcher.log."); return }
        if let server=server, !server.isRunning {fail("The local service stopped. Check ~/Library/Application Support/Local Explainer/launcher.log.");return}
        let url=URL(string:"http://127.0.0.1:\(port)/?token=\(token)")!
        URLSession.shared.dataTask(with:url) {_,response,error in
            DispatchQueue.main.async {
                if error==nil && (response as? HTTPURLResponse)?.statusCode==200 {self.web.load(URLRequest(url:url)); self.loading.removeFromSuperview()}
                else {DispatchQueue.main.asyncAfter(deadline:.now()+0.5){self.poll()}}
            }
        }.resume()
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let index=CommandLine.arguments.firstIndex(of:"--snapshot"), CommandLine.arguments.count>index+1 {
            let target=CommandLine.arguments[index+1]
            DispatchQueue.main.asyncAfter(deadline:.now()+2) {
                self.web.takeSnapshot(with:nil) {image,error in
                    if let image=image,let data=image.tiffRepresentation,let bitmap=NSBitmapImageRep(data:data),let png=bitmap.representation(using:.png,properties:[:]) {
                        try? png.write(to:URL(fileURLWithPath:target))
                    }
                    NSApp.terminate(nil)
                }
            }
        }
    }
    func fail(_ message:String) {loading.stringValue=message;loading.font=NSFont.systemFont(ofSize:13);loading.maximumNumberOfLines=4;loading.frame.size.height=100}
    @objc func about() {NSApp.orderFrontStandardAboutPanel(options:[.applicationName:"Local Explainer",.applicationVersion:"0.1.0",.credits:NSAttributedString(string:"Local AI narration and Blender video composition.\nA development build for Apple Silicon macOS.")])}
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool {true}
    func applicationWillTerminate(_ notification:Notification) { if let server=server,server.isRunning {server.terminate()} }
    func webView(_ webView:WKWebView,runOpenPanelWith parameters:WKOpenPanelParameters,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping([URL]?)->Void) {
        let panel=NSOpenPanel(); panel.allowsMultipleSelection=false; panel.canChooseDirectories=false
        panel.beginSheetModal(for:window){result in completionHandler(result == .OK ? panel.urls:nil)}
    }
    func webView(_ webView:WKWebView,decidePolicyFor navigationAction:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void) {
        if let url=navigationAction.request.url, url.host != "127.0.0.1",url.scheme != "about" { decisionHandler(.cancel); return }
        decisionHandler(.allow)
    }
}
let app=NSApplication.shared
let delegate=AppDelegate()
app.delegate=delegate
app.setActivationPolicy(.regular)
app.run()
