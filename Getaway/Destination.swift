import CoreLocation

struct Destination: Identifiable {
    enum Kind {
        case beach, hike, lookout

        var label: String {
            switch self {
            case .beach: return "Beach"
            case .hike: return "Hike"
            case .lookout: return "Lookout"
            }
        }
    }

    let id = UUID()
    let name: String
    let kind: Kind
    let driveMinutes: Int
    let summary: String
    let coordinate: CLLocationCoordinate2D
}

extension Destination {
    // Placeholder data until stage 2 replaces it with the Places API.
    // Coordinates and drive times are approximate.
    static let samples: [Destination] = [
        Destination(name: "Sorrento Back Beach", kind: .beach, driveMinutes: 95,
                    summary: "Rock pools. Car park fills early.",
                    coordinate: CLLocationCoordinate2D(latitude: -38.346, longitude: 144.733)),
        Destination(name: "Erskine Falls", kind: .hike, driveMinutes: 135,
                    summary: "Shaded rainforest walk near Lorne.",
                    coordinate: CLLocationCoordinate2D(latitude: -38.511, longitude: 143.920)),
        Destination(name: "Mount Donna Buang", kind: .lookout, driveMinutes: 90,
                    summary: "High up, usually cooler than the city.",
                    coordinate: CLLocationCoordinate2D(latitude: -37.707, longitude: 145.684)),
        Destination(name: "Cape Schanck", kind: .hike, driveMinutes: 85,
                    summary: "Boardwalk to the lighthouse.",
                    coordinate: CLLocationCoordinate2D(latitude: -38.493, longitude: 144.886))
    ]
}
