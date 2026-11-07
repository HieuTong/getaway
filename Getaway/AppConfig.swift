import Foundation

enum AppConfig {
    // Read once, on first use. Info.plist received these values from Secrets.xcconfig at build time.
    static let googleAPIKey: String = {
        guard let key = Bundle.main.object(forInfoDictionaryKey: "GMSApiKey") as? String,
              !key.isEmpty,
              key != "YOUR_IOS_KEY_HERE" else {
            fatalError("Missing Google Maps API key. Copy Secrets.example.xcconfig to Secrets.xcconfig and paste your key.")
        }
        return key
    }()

    static let agentBaseURL: URL = {
        guard let value = Bundle.main.object(forInfoDictionaryKey: "AgentBaseURL") as? String,
              let url = URL(string: value),
              url.scheme != nil else {
            fatalError("Missing AGENT_BASE_URL in Secrets.xcconfig, for example: AGENT_BASE_URL = http:/$()/127.0.0.1:8000")
        }
        return url
    }()

    static let bundleID = Bundle.main.bundleIdentifier ?? ""
}
