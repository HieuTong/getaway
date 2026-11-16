import UIKit

/// Hands turn-by-turn navigation to the Google Maps app (or google.com/maps if the app isn't installed).
/// Needs no API key and no billing: the user's Google Maps app does all the routing.
/// The in-app version (NavigationViewController, Navigation SDK) needs a billing-enabled Cloud project.
enum GoogleMapsHandoff {

    static func openDirections(to destination: Destination) {
        var components = URLComponents(string: "https://www.google.com/maps/dir/")!
        components.queryItems = [
            URLQueryItem(name: "api", value: "1"),
            // Coordinates say where; the place ID makes Google pick the exact place, not a nearby address.
            URLQueryItem(name: "destination",
                         value: "\(destination.coordinate.latitude),\(destination.coordinate.longitude)"),
            URLQueryItem(name: "destination_place_id", value: destination.id),
            URLQueryItem(name: "travelmode", value: "driving"),
            URLQueryItem(name: "dir_action", value: "navigate") // start guidance straight away
        ]
        guard let url = components.url else { return }
        UIApplication.shared.open(url)
    }
}
