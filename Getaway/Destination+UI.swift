import UIKit

// How each kind of destination looks. Shared by the map pins and the detail sheet,
// so a beach is the same colour everywhere.
extension Destination.Kind {
    var color: UIColor {
        switch self {
        case .beach: return .systemTeal
        case .hike: return .systemGreen
        case .lookout: return .systemOrange
        }
    }

    var symbolName: String {
        switch self {
        case .beach: return "beach.umbrella.fill"
        case .hike: return "figure.hiking"
        case .lookout: return "binoculars.fill"
        }
    }

    var singularLabel: String {
        switch self {
        case .beach: return "Beach"
        case .hike: return "Hike"
        case .lookout: return "Lookout"
        }
    }
}
