import CoreLocation

struct Destination: Identifiable {
    enum Kind: CaseIterable {
        case beach, hike, lookout

        var label: String {
            switch self {
            case .beach: return "Beaches"
            case .hike: return "Hikes"
            case .lookout: return "Lookouts"
            }
        }
    }

    let id: String // Google place ID: stable, and used to cache routes per place
    let name: String
    let kind: Kind
    let coordinate: CLLocationCoordinate2D
    let rating: Float?
    let address: String?
    let attributions: NSAttributedString? // Places terms: show these wherever place details appear
}
