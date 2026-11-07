import CoreLocation

enum LocationError: LocalizedError {
    case denied

    var errorDescription: String? {
        "Location access is off. Turn it on in Settings → Privacy & Security → Location Services → Getaway."
    }
}

/// Answers one question, "where am I right now?", as an async call.
@MainActor
final class LocationProvider: NSObject, CLLocationManagerDelegate {

    static let shared = LocationProvider()

    private let manager = CLLocationManager()
    private var waiters: [CheckedContinuation<CLLocationCoordinate2D, Error>] = []

    private override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters // street-level is plenty for drive times, and much faster
    }

    func currentCoordinate() async throws -> CLLocationCoordinate2D {
        // A fix from the last 2 minutes is good enough: no need to wake the GPS again.
        if let recent = manager.location, recent.timestamp.timeIntervalSinceNow > -120 {
            return recent.coordinate
        }
        return try await withCheckedThrowingContinuation { continuation in
            waiters.append(continuation)
            if waiters.count == 1 { requestIfAuthorized() } // only the first caller starts a request
        }
    }

    private func requestIfAuthorized() {
        switch manager.authorizationStatus {
        case .notDetermined:
            manager.requestWhenInUseAuthorization() // the answer arrives in locationManagerDidChangeAuthorization
        case .authorizedWhenInUse, .authorizedAlways:
            manager.requestLocation() // one-shot fix, then the GPS turns itself off
        default:
            finish(.failure(LocationError.denied))
        }
    }

    private func finish(_ result: Result<CLLocationCoordinate2D, Error>) {
        let pending = waiters
        waiters = []
        pending.forEach { $0.resume(with: result) }
    }

    // MARK: - CLLocationManagerDelegate (called on the main thread, where the manager was created)

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        MainActor.assumeIsolated {
            guard !waiters.isEmpty, manager.authorizationStatus != .notDetermined else { return }
            requestIfAuthorized()
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let coordinate = locations.last?.coordinate else { return }
        MainActor.assumeIsolated { finish(.success(coordinate)) }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        MainActor.assumeIsolated { finish(.failure(error)) }
    }
}
