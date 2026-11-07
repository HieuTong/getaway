import UIKit
import GoogleMaps

final class ViewController: UIViewController {

    private var mapView: GMSMapView!
    private let placesService = PlacesService()
    private let routesService = RoutesService()
    private var searchTask: Task<Void, Never>?
    private var routeLine: GMSPolyline?
    private var isShowingDetail = false

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
        updateMapPadding()
    }

    /// Tells the SDK which part of the map is actually visible, so camera fitting
    /// and the Google logo avoid the status bar, the segmented control and the sheet.
    private func updateMapPadding() {
        let bottom = isShowingDetail ? view.bounds.height * 0.5 : view.safeAreaInsets.bottom
        mapView.padding = UIEdgeInsets(top: view.safeAreaInsets.top + 52, left: 0, bottom: bottom, right: 0)
    }

    // MARK: - Setup

    private func setUpMap() {
        let options = GMSMapViewOptions()
        options.camera = GMSCameraPosition(latitude: -37.8136, longitude: 144.9631, zoom: 8) // Melbourne CBD
        mapView = GMSMapView(options: options)
        mapView.delegate = self
        mapView.isMyLocationEnabled = true
        mapView.settings.myLocationButton = true
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

    // MARK: - Loading destinations

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
        mapView.clear() // removes markers and any route line from before
        routeLine = nil
        guard !destinations.isEmpty else {
            showMessage("No places found", detail: "Try another category.")
            return
        }
        var bounds = GMSCoordinateBounds()
        for destination in destinations {
            let marker = GMSMarker(position: destination.coordinate)
            marker.title = destination.name
            marker.snippet = destination.subtitle
            marker.icon = GMSMarker.markerImage(with: destination.kind.color)
            marker.userData = destination // lets a tapped marker tell us which place it is
            marker.map = mapView
            bounds = bounds.includingCoordinate(destination.coordinate)
        }
        mapView.animate(with: GMSCameraUpdate.fit(bounds, withPadding: 60))
    }

    // MARK: - Detail sheet and route

    private func showDetail(for destination: Destination) {
        let detail = DestinationDetailViewController(
            destination: destination,
            routesService: routesService,
            onBestRoute: { [weak self] route in self?.drawRoute(route) },
            onDismiss: { [weak self] in
                self?.isShowingDetail = false
                self?.updateMapPadding()
            }
        )
        if let sheet = detail.sheetPresentationController {
            sheet.detents = [.medium(), .large()]
            sheet.prefersGrabberVisible = true
            sheet.largestUndimmedDetentIdentifier = .medium // map stays bright and usable above the sheet
        }

        let presentDetail = { [weak self] in
            guard let self else { return }
            isShowingDetail = true
            updateMapPadding()
            present(detail, animated: true)
        }
        // Only one sheet at a time: close the old one first, then open the new one.
        if presentedViewController != nil {
            dismiss(animated: true, completion: presentDetail)
        } else {
            presentDetail()
        }
    }

    private func drawRoute(_ route: RouteEstimate) {
        routeLine?.map = nil
        guard let encoded = route.encodedPolyline,
              let path = GMSPath(fromEncodedPath: encoded) else { return }
        let line = GMSPolyline(path: path)
        line.strokeWidth = 5
        line.strokeColor = .systemBlue
        line.map = mapView
        routeLine = line
        mapView.animate(with: GMSCameraUpdate.fit(GMSCoordinateBounds(path: path), withPadding: 60))
    }

    // MARK: - Alerts

    private func showError(_ error: Error) {
        showMessage("Search failed", detail: error.localizedDescription)
    }

    private func showMessage(_ title: String, detail: String) {
        let alert = UIAlertController(title: title, message: detail, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "OK", style: .default))
        present(alert, animated: true)
    }
}

// MARK: - GMSMapViewDelegate

extension ViewController: GMSMapViewDelegate {
    func mapView(_ mapView: GMSMapView, didTap marker: GMSMarker) -> Bool {
        guard let destination = marker.userData as? Destination else { return false }
        showDetail(for: destination)
        return false // keep the SDK default: centre on the marker and show its info window
    }
}

// UI-only knowledge lives with the UI, not in the model.
private extension Destination {
    var subtitle: String {
        let ratingText = rating.map { String(format: "★ %.1f", $0) }
        return [ratingText, address].compactMap { $0 }.joined(separator: " · ")
    }
}

