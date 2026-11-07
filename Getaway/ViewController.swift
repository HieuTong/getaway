import UIKit
import GoogleMaps

final class ViewController: UIViewController {

    private var mapView: GMSMapView!
    private var destinationBounds = GMSCoordinateBounds()
    private var hasFittedCamera = false

    override func viewDidLoad() {
        super.viewDidLoad()
        setUpMap()
        addDestinationMarkers()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        // Fit the camera only once, after Auto Layout has given the map its real size.
        guard !hasFittedCamera, mapView.bounds.width > 0 else { return }
        hasFittedCamera = true
        mapView.moveCamera(GMSCameraUpdate.fit(destinationBounds, withPadding: 60))
    }

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

    private func addDestinationMarkers() {
        for destination in Destination.samples {
            let marker = GMSMarker(position: destination.coordinate)
            marker.title = destination.name
            marker.snippet = "\(destination.kind.label) · \(destination.driveMinutes) min drive"
            marker.icon = GMSMarker.markerImage(with: destination.kind.markerColor)
            marker.map = mapView // setting .map is what actually puts the marker on screen
            destinationBounds = destinationBounds.includingCoordinate(destination.coordinate)
        }
    }
}

// UI-only knowledge lives with the UI, not in the model.
private extension Destination.Kind {
    var markerColor: UIColor {
        switch self {
        case .beach: return .systemTeal
        case .hike: return .systemGreen
        case .lookout: return .systemOrange
        }
    }
}
