import Foundation

enum AppConfig {
    // Read once, on first use. Info.plist received the value from Secrets.xcconfig at build time.
    static let googleAPIKey: String = {
        guard let key = Bundle.main.object(forInfoDictionaryKey: "GMSApiKey") as? String,
              !key.isEmpty,
              key != "YOUR_IOS_KEY_HERE" else {
            fatalError("Missing Google Maps API key. Copy Secrets.example.xcconfig to Secrets.xcconfig and paste your key.")
        }
        return key
    }()

    static let bundleID = Bundle.main.bundleIdentifier ?? ""
}
