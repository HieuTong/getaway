import CoreLocation

struct Destination: Identifiable {
    enum Kind: CaseIterable {
        case beach, hike, lookout, suggestion

        /// The categories the user can browse with the segmented control. AI picks aren't a category.
        static let browsable: [Kind] = [.beach, .hike, .lookout]

        var label: String {
            switch self {
            case .beach: return "Beaches"
            case .hike: return "Hikes"
            case .lookout: return "Lookouts"
            case .suggestion: return "Suggested"
            }
        }
    }

    let id: String // Google place ID: stable, and used to cache routes and to navigate
    let name: String
    let kind: Kind
    let coordinate: CLLocationCoordinate2D
    let rating: Float?
    let address: String?
    let attributions: NSAttributedString? // Places terms: show these wherever place details appear
    var agentReason: String? = nil        // why the AI agent picked this place, if it did
}
