import UIKit
import CoreLocation
import GoogleMaps
import GoogleNavigation

final class NavigationViewController: UIViewController {

    private let destination: Destination
    private var mapView: GMSMapView!
    private var hasStarted = false

    init(destination: Destination) {
        self.destination = destination
        super.init(nibName: nil, bundle: nil)
        modalPresentationStyle = .fullScreen // navigation takes over the whole screen, like Google Maps
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground

        mapView = GMSMapView(options: GMSMapViewOptions())
        let bottomBar = makeBottomBar()
        mapView.translatesAutoresizingMaskIntoConstraints = false
        bottomBar.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(mapView)
        view.addSubview(bottomBar)

        NSLayoutConstraint.activate([
            mapView.topAnchor.constraint(equalTo: view.topAnchor),
            mapView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            mapView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            mapView.bottomAnchor.constraint(equalTo: bottomBar.topAnchor), // Google's ETA footer sits just above our bar
            bottomBar.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            bottomBar.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            bottomBar.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        UIApplication.shared.isIdleTimerDisabled = true // the SDK doesn't stop the screen dimming, so we do
        guard !hasStarted else { return }
        hasStarted = true
        requestTermsThenStart()
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        UIApplication.shared.isIdleTimerDisabled = false
    }

    // MARK: - Bottom bar

    private func makeBottomBar() -> UIView {
        let bar = UIView()
        bar.backgroundColor = .systemBackground

        let titleLabel = UILabel()
        titleLabel.text = destination.name
        titleLabel.font = .preferredFont(forTextStyle: .headline)
        titleLabel.adjustsFontForContentSizeCategory = true
        titleLabel.numberOfLines = 1

        var endConfig = UIButton.Configuration.filled()
        endConfig.title = "End"
        endConfig.baseBackgroundColor = .systemRed
        endConfig.cornerStyle = .capsule
        endConfig.buttonSize = .large
        let endButton = UIButton(configuration: endConfig, primaryAction: UIAction { [weak self] _ in
            self?.endNavigation()
        })
        endButton.setContentHuggingPriority(.required, for: .horizontal)

        let row = UIStackView(arrangedSubviews: [titleLabel, endButton])
        row.spacing = 12
        row.alignment = .center
        row.translatesAutoresizingMaskIntoConstraints = false
        bar.addSubview(row)

        NSLayoutConstraint.activate([
            row.topAnchor.constraint(equalTo: bar.topAnchor, constant: 12),
            row.leadingAnchor.constraint(equalTo: bar.layoutMarginsGuide.leadingAnchor),
            row.trailingAnchor.constraint(equalTo: bar.layoutMarginsGuide.trailingAnchor),
            row.bottomAnchor.constraint(equalTo: bar.safeAreaLayoutGuide.bottomAnchor, constant: -12)
        ])
        return bar
    }

    // MARK: - Navigation flow

    private func requestTermsThenStart() {
        // Google requires users to accept the Navigation terms before guidance can start.
        // The dialog only appears the first time; after that the callback fires straight away.
        let options = GMSNavigationTermsAndConditionsOptions(companyName: "Getaway")
        GMSNavigationServices.showTermsAndConditionsDialogIfNeeded(with: options) { [weak self] accepted in
            guard let self else { return }
            guard accepted else {
                endNavigation()
                return
            }
            mapView.isNavigationEnabled = true
            mapView.settings.compassButton = true
            waitForLocationThenStart()
        }
    }

    /// Navigation starts from where the phone really is, so we need location permission and a GPS fix first.
    private func waitForLocationThenStart() {
        Task { [weak self] in
            do {
                _ = try await LocationProvider.shared.currentCoordinate()
                self?.startGuidance()
            } catch {
                self?.showFailure(error.localizedDescription)
            }
        }
    }

    private func startGuidance() {
        // We kept Google's place ID from stage 2, so the SDK routes to the exact place, not a guessed address.
        guard let waypoint = GMSNavigationWaypoint(placeID: destination.id, title: destination.name) else {
            showFailure("This place can't be used as a navigation destination.")
            return
        }

        // With no origin given, the SDK routes from the device's current GPS position.
        mapView.navigator?.setDestinations([waypoint]) { [weak self] routeStatus in
            guard let self else { return }
            guard routeStatus == .OK else {
                showFailure("Google couldn't plan a route (status \(routeStatus.rawValue)). Check your connection and that the Navigation SDK is enabled for your API key.")
                return
            }
            mapView.navigator?.isGuidanceActive = true
            mapView.cameraMode = .following
        }
    }

    private func endNavigation() {
        mapView.navigator?.isGuidanceActive = false
        mapView.navigator?.clearDestinations()
        mapView.isNavigationEnabled = false
        dismiss(animated: true)
    }

    private func showFailure(_ message: String) {
        let alert = UIAlertController(title: "Can't start navigation", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "OK", style: .default) { [weak self] _ in
            self?.endNavigation()
        })
        present(alert, animated: true)
    }
}
