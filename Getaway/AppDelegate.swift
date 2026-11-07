import UIKit
import GoogleMaps
import GooglePlacesSwift

@main
class AppDelegate: UIResponder, UIApplicationDelegate {

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        // Read the key that Info.plist received from Secrets.xcconfig at build time.
        guard let apiKey = Bundle.main.object(forInfoDictionaryKey: "GMSApiKey") as? String,
              !apiKey.isEmpty,
              apiKey != "YOUR_IOS_KEY_HERE" else {
            fatalError("Missing Google Maps API key. Copy Secrets.example.xcconfig to Secrets.xcconfig and paste your key.")
        }
        GMSServices.provideAPIKey(apiKey)
        _ = PlacesClient.provideAPIKey(apiKey) // separate SDK, so it needs the key separately
        return true
    }

    func application(_ application: UIApplication,
                     configurationForConnecting connectingSceneSession: UISceneSession,
                     options: UIScene.ConnectionOptions) -> UISceneConfiguration {
        UISceneConfiguration(name: "Default Configuration", sessionRole: connectingSceneSession.role)
    }
}
