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
            fatalError("Missing AGENT_BASE_URL in Secrets.xcconfig, for example: AGENT_BASE_URL = https:/$()/getaway-agent.onrender.com")
        }
        return url
    }()

    static let agentAccessToken: String = {
        guard let token = Bundle.main.object(forInfoDictionaryKey: "AgentAccessToken") as? String,
              !token.isEmpty else {
            fatalError("Missing AGENT_ACCESS_TOKEN in Secrets.xcconfig. Copy it from Render's Environment tab.")
        }
        return token
    }()

    static let bundleID = Bundle.main.bundleIdentifier ?? ""
}
