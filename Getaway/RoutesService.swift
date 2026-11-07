import CoreLocation

struct RouteEstimate {
    let departure: Date
    let duration: TimeInterval // seconds, predicted for that departure time
    let distanceMeters: Int
    let encodedPolyline: String?
}

enum RoutesError: LocalizedError {
    case api(String)
    case noRoute

    var errorDescription: String? {
        switch self {
        case .api(let message): return message
        case .noRoute: return "Google found no driving route."
        }
    }
}

@MainActor
final class RoutesService {

    private var cache: [String: [RouteEstimate]] = [:] // keyed by destination + rounded origin + day

    private let endpoint = URL(string: "https://routes.googleapis.com/directions/v2:computeRoutes")!
    private let apiKey = AppConfig.googleAPIKey
    private let bundleID = AppConfig.bundleID

    /// Drive estimates from the user's current location for several departure times on `day`
    /// (tomorrow when nil), fetched in parallel, sorted by departure.
    func leaveTimeEstimates(to destination: Destination, on day: Date? = nil) async throws -> [RouteEstimate] {
        let departures = Self.candidateDepartures(on: day)
        guard let firstDeparture = departures.first else { return [] }

        let origin = try await LocationProvider.shared.currentCoordinate()
        // The day is part of the key: Boxing Day traffic is not tomorrow's traffic.
        let cacheKey = String(format: "%@|%.2f,%.2f|%d",
                              destination.id, origin.latitude, origin.longitude,
                              Int(firstDeparture.timeIntervalSince1970))
        if let cached = cache[cacheKey] { return cached }

        let target = destination.coordinate
        let estimates = try await withThrowingTaskGroup(of: RouteEstimate.self) { group in
            for departure in departures {
                group.addTask {
                    try await self.computeRoute(from: origin, to: target, departingAt: departure)
                }
            }
            var results: [RouteEstimate] = []
            for try await estimate in group { results.append(estimate) }
            return results.sorted { $0.departure < $1.departure }
        }

        cache[cacheKey] = estimates
        return estimates
    }

    /// 7am, 9am, 11am and 1pm Melbourne time on `day` (tomorrow when nil), skipping any time already past.
    static func candidateDepartures(on day: Date? = nil, now: Date = Date()) -> [Date] {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Australia/Melbourne")!
        let startOfToday = calendar.startOfDay(for: now)
        let tripDay = day.map { calendar.startOfDay(for: $0) }
            ?? calendar.date(byAdding: .day, value: 1, to: startOfToday)!
        let earliest = now.addingTimeInterval(5 * 60) // Routes only predicts departures in the future
        return [7, 9, 11, 13]
            .compactMap { calendar.date(bySettingHour: $0, minute: 0, second: 0, of: tripDay) }
            .filter { $0 > earliest }
    }

    // MARK: - One Routes API call

    private nonisolated func computeRoute(from origin: CLLocationCoordinate2D,
                                          to destination: CLLocationCoordinate2D,
                                          departingAt departure: Date) async throws -> RouteEstimate {
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "X-Goog-Api-Key")
        // The key is restricted to iOS apps; this header tells Google which app is calling.
        request.setValue(bundleID, forHTTPHeaderField: "X-Ios-Bundle-Identifier")
        // Field mask: only the fields we use. Required by the Routes API, and it keeps responses small.
        request.setValue("routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline",
                         forHTTPHeaderField: "X-Goog-FieldMask")

        let body = ComputeRoutesRequest(origin: .init(origin),
                                        destination: .init(destination),
                                        departureTime: ISO8601DateFormatter().string(from: departure))
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else {
            let message = (try? JSONDecoder().decode(GoogleErrorResponse.self, from: data))?.error.message
            throw RoutesError.api(message ?? "HTTP \(status)")
        }

        let decoded = try JSONDecoder().decode(ComputeRoutesResponse.self, from: data)
        // Google sends durations as strings like "5520s".
        guard let route = decoded.routes?.first,
              let seconds = Double(route.duration.dropLast()) else { throw RoutesError.noRoute }
        return RouteEstimate(departure: departure,
                             duration: seconds,
                             distanceMeters: route.distanceMeters ?? 0,
                             encodedPolyline: route.polyline?.encodedPolyline)
    }
}

// MARK: - JSON shapes (private: nothing outside this file needs Google's wire format)

private struct ComputeRoutesRequest: Encodable {
    struct Waypoint: Encodable {
        struct Location: Encodable {
            struct LatLng: Encodable { let latitude: Double; let longitude: Double }
            let latLng: LatLng
        }
        let location: Location

        init(_ coordinate: CLLocationCoordinate2D) {
            location = Location(latLng: .init(latitude: coordinate.latitude, longitude: coordinate.longitude))
        }
    }

    let origin: Waypoint
    let destination: Waypoint
    let travelMode = "DRIVE"
    let routingPreference = "TRAFFIC_AWARE_OPTIMAL" // needed for traffic predictions at a future departureTime
    let departureTime: String
}

private struct ComputeRoutesResponse: Decodable {
    struct Route: Decodable {
        struct Polyline: Decodable { let encodedPolyline: String }
        let distanceMeters: Int?
        let duration: String
        let polyline: Polyline?
    }
    let routes: [Route]?
}

private struct GoogleErrorResponse: Decodable {
    struct Body: Decodable { let message: String }
    let error: Body
}
