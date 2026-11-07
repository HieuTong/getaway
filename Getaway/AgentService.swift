import CoreLocation

/// The backend's answer. Property names are camelCase; the decoder maps them from the API's snake_case.
struct AgentPlan: Decodable {
    struct Suggestion: Decodable {
        let placeId: String
        let name: String
        let latitude: Double
        let longitude: Double
        let reason: String
        let driveMinutes: Int?
        let leaveBy: String?
    }

    let summary: String
    let suggestions: [Suggestion]
}

enum AgentError: LocalizedError {
    case server(String)

    var errorDescription: String? {
        switch self {
        case .server(let message): return message
        }
    }
}

final class AgentService {

    private let session: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 90 // the agent makes several tool calls, plus retries
        return URLSession(configuration: configuration)
    }()

    // "yyyy-MM-dd" in Melbourne time. en_US_POSIX keeps the format fixed whatever the phone's language or calendar.
    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "Australia/Melbourne")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    func plan(query: String, from origin: CLLocationCoordinate2D, on tripDate: Date) async throws -> AgentPlan {
        var request = URLRequest(url: AppConfig.agentBaseURL.appendingPathComponent("plan"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = PlanRequest(query: query,
                               originLatitude: origin.latitude,
                               originLongitude: origin.longitude,
                               tripDate: Self.dayFormatter.string(from: tripDate))
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase // originLatitude -> origin_latitude
        request.httpBody = try encoder.encode(body)

        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else {
            // Our backend explains failures in {"detail": "..."}; show that to the user if we can.
            let detail = (try? JSONDecoder().decode(ErrorBody.self, from: data))?.detail
            throw AgentError.server(detail ?? "The trip planner is unavailable (HTTP \(status)). Try again in a moment.")
        }

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase // place_id -> placeId
        return try decoder.decode(AgentPlan.self, from: data)
    }
}

private struct PlanRequest: Encodable {
    let query: String
    let originLatitude: Double
    let originLongitude: Double
    let tripDate: String
}

private struct ErrorBody: Decodable {
    let detail: String
}
