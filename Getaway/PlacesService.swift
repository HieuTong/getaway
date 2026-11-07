import CoreLocation
import GooglePlacesSwift

@MainActor
final class PlacesService {

    private let melbourne = CLLocationCoordinate2D(latitude: -37.8136, longitude: 144.9631)
    private var cache: [Destination.Kind: [Destination]] = [:]

    func searchDestinations(of kind: Destination.Kind) async throws -> [Destination] {
        if let cached = cache[kind] { return cached }

        let request = SearchByTextRequest(
            textQuery: kind.searchQuery,
            placeProperties: [.placeID, .displayName, .coordinate, .rating, .formattedAddress],
            locationBias: CircularCoordinateRegion(center: melbourne, radius: 50_000),
            maxResultCount: 10,
            isOpenNow: false, // the default (true) would hide beaches and trails, which have no opening hours
            regionCode: "AU"
        )

        switch await PlacesClient.shared.responseForSearchByText(with: request) {
        case .success(let response):
            let destinations = (response.places ?? []).compactMap { place -> Destination? in
                guard let id = place.placeID, let name = place.displayName else { return nil }
                return Destination(id: id, name: name, kind: kind, coordinate: place.location,
                                   rating: place.rating, address: place.formattedAddress,
                                   attributions: place.legacyAttributions)
            }
            cache[kind] = destinations
            return destinations
        case .failure(let error):
            throw error
        }
    }
}

// What to search for is a Google-specific detail, so it lives here, not in the model.
private extension Destination.Kind {
    var searchQuery: String {
        switch self {
        case .beach: return "beaches near Melbourne, Victoria"
        case .hike: return "bushwalking trails near Melbourne, Victoria"
        case .lookout: return "scenic lookouts near Melbourne, Victoria"
        case .suggestion: return "" // AI picks come from the agent, never from a category search
        }
    }
}
