import UIKit
import GoogleMaps

final class ViewController: UIViewController {

    private var mapView: GMSMapView!
    private let placesService = PlacesService()
    private var searchTask: Task<Void, Never>?

    private lazy var kindControl: UISegmentedControl = {
        let control = UISegmentedControl(items: Destination.Kind.allCases.map(\.label))
        control.selectedSegmentIndex = 0
        control.backgroundColor = .systemBackground
        control.addTarget(self, action: #selector(kindChanged), for: .valueChanged)
        control.translatesAutoresizingMaskIntoConstraints = false
        return control
    }()

    private let spinner: UIActivityIndicatorView = {
        let spinner = UIActivityIndicatorView(style: .large)
        spinner.hidesWhenStopped = true
        spinner.translatesAutoresizingMaskIntoConstraints = false
        return spinner
    }()

    override func viewDidLoad() {
        super.viewDidLoad()
        setUpMap()
        setUpControls()
        loadDestinations(of: .beach)
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        // Safe-area insets are only known after layout. Padding keeps pins, the Google logo
        // and camera fitting clear of the status bar and the segmented control.
        mapView.padding = UIEdgeInsets(top: view.safeAreaInsets.top + 52, left: 0,
                                       bottom: view.safeAreaInsets.bottom, right: 0)
    }

    // MARK: - Setup

    private func setUpMap() {
        let options = GMSMapViewOptions()
        options.camera = GMSCameraPosition(latitude: -37.8136, longitude: 144.9631, zoom: 8) // Melbourne CBD
        mapView = GMSMapView(options: options)
        mapView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(mapView)
        NSLayoutConstraint.activate([
            mapView.topAnchor.constraint(equalTo: view.topAnchor),
            mapView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            mapView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            mapView.trailingAnchor.constraint(equalTo: view.trailingAnchor)
        ])
    }

    private func setUpControls() {
        view.addSubview(kindControl)
        view.addSubview(spinner)
        NSLayoutConstraint.activate([
            kindControl.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 8),
            kindControl.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
            kindControl.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),
            spinner.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            spinner.centerYAnchor.constraint(equalTo: view.centerYAnchor)
        ])
    }

    // MARK: - Loading

    @objc private func kindChanged() {
        let kind = Destination.Kind.allCases[kindControl.selectedSegmentIndex]
        loadDestinations(of: kind)
    }

    private func loadDestinations(of kind: Destination.Kind) {
        searchTask?.cancel() // a fast second tap must not let the first, slower search win
        spinner.startAnimating()
        searchTask = Task { [weak self] in
            guard let self else { return }
            do {
                let destinations = try await placesService.searchDestinations(of: kind)
                guard !Task.isCancelled else { return }
                show(destinations)
            } catch {
                guard !Task.isCancelled else { return }
                showError(error)
            }
            spinner.stopAnimating()
        }
    }

    private func show(_ destinations: [Destination]) {
        mapView.clear() // removes all markers from the previous search
        guard !destinations.isEmpty else {
            showMessage("No places found", detail: "Try another category.")
            return
        }
        var bounds = GMSCoordinateBounds()
        for destination in destinations {
            let marker = GMSMarker(position: destination.coordinate)
            marker.title = destination.name
            marker.snippet = destination.subtitle
            marker.icon = GMSMarker.markerImage(with: destination.kind.markerColor)
            marker.map = mapView
            bounds = bounds.includingCoordinate(destination.coordinate)
        }
        mapView.animate(with: GMSCameraUpdate.fit(bounds, withPadding: 60))
    }

    private func showError(_ error: Error) {
        showMessage("Search failed", detail: error.localizedDescription)
    }

    private func showMessage(_ title: String, detail: String) {
        let alert = UIAlertController(title: title, message: detail, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "OK", style: .default))
        present(alert, animated: true)
    }
}

// UI-only knowledge lives with the UI, not in the model.
private extension Destination {
    var subtitle: String {
        let ratingText = rating.map { String(format: "★ %.1f", $0) }
        return [ratingText, address].compactMap { $0 }.joined(separator: " · ")
    }
}

private extension Destination.Kind {
    var markerColor: UIColor {
        switch self {
        case .beach: return .systemTeal
        case .hike: return .systemGreen
        case .lookout: return .systemOrange
        }
    }
}
