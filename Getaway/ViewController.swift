import UIKit
import GoogleMaps

final class ViewController: UIViewController {

    private var mapView: GMSMapView!
    private let placesService = PlacesService()
    private let routesService = RoutesService()
    private let agentService = AgentService()
    private var searchTask: Task<Void, Never>? // the current category search OR agent request
    private var routeLine: GMSPolyline?
    private var isShowingDetail = false
    private var agentTripDate: Date? // the day the AI picks on the map were planned for

    private lazy var kindControl: UISegmentedControl = {
        let control = UISegmentedControl(items: Destination.Kind.browsable.map(\.label))
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

    private lazy var askButton: UIButton = {
        var config = UIButton.Configuration.filled()
        config.title = "Ask Getaway"
        config.image = UIImage(systemName: "sparkles")
        config.imagePadding = 8
        config.cornerStyle = .capsule
        config.buttonSize = .large
        let button = UIButton(configuration: config, primaryAction: UIAction { [weak self] _ in
            self?.showAsk()
        })
        button.layer.shadowColor = UIColor.black.cgColor
        button.layer.shadowOpacity = 0.2
        button.layer.shadowRadius = 8
        button.layer.shadowOffset = CGSize(width: 0, height: 4)
        button.translatesAutoresizingMaskIntoConstraints = false
        return button
    }()

    private let summaryLabel: UILabel = {
        let label = UILabel()
        label.font = .preferredFont(forTextStyle: .subheadline)
        label.adjustsFontForContentSizeCategory = true
        label.numberOfLines = 3
        label.translatesAutoresizingMaskIntoConstraints = false
        return label
    }()

    private lazy var summaryCard: UIView = {
        let card = UIView()
        card.backgroundColor = .systemBackground
        card.layer.cornerRadius = 12
        card.layer.cornerCurve = .continuous
        card.layer.shadowColor = UIColor.black.cgColor
        card.layer.shadowOpacity = 0.12
        card.layer.shadowRadius = 6
        card.isHidden = true
        card.translatesAutoresizingMaskIntoConstraints = false
        card.addSubview(summaryLabel)
        NSLayoutConstraint.activate([
            summaryLabel.topAnchor.constraint(equalTo: card.topAnchor, constant: 12),
            summaryLabel.bottomAnchor.constraint(equalTo: card.bottomAnchor, constant: -12),
            summaryLabel.leadingAnchor.constraint(equalTo: card.leadingAnchor, constant: 14),
            summaryLabel.trailingAnchor.constraint(equalTo: card.trailingAnchor, constant: -14)
        ])
        return card
    }()

    private lazy var planningOverlay: UIVisualEffectView = {
        let overlay = UIVisualEffectView(effect: UIBlurEffect(style: .systemMaterial))
        overlay.layer.cornerRadius = 16
        overlay.layer.cornerCurve = .continuous
        overlay.clipsToBounds = true
        overlay.isHidden = true
        overlay.translatesAutoresizingMaskIntoConstraints = false

        let indicator = UIActivityIndicatorView(style: .medium)
        indicator.startAnimating()
        let label = UILabel()
        label.text = "Planning your trip…"
        label.font = .preferredFont(forTextStyle: .headline)
        let row = UIStackView(arrangedSubviews: [indicator, label])
        row.spacing = 10
        row.translatesAutoresizingMaskIntoConstraints = false
        overlay.contentView.addSubview(row)
        NSLayoutConstraint.activate([
            row.topAnchor.constraint(equalTo: overlay.contentView.topAnchor, constant: 16),
            row.bottomAnchor.constraint(equalTo: overlay.contentView.bottomAnchor, constant: -16),
            row.leadingAnchor.constraint(equalTo: overlay.contentView.leadingAnchor, constant: 20),
            row.trailingAnchor.constraint(equalTo: overlay.contentView.trailingAnchor, constant: -20)
        ])
        return overlay
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

    /// Tells the SDK which part of the map is actually visible, so camera fitting and the Google logo
    /// avoid the status bar, the category control, the summary card, the Ask button and the sheet.
    private func updateMapPadding() {
        let summaryHeight = summaryCard.isHidden ? 0 : summaryCard.bounds.height + 8
        let top = view.safeAreaInsets.top + 52 + summaryHeight
        let bottom = isShowingDetail ? view.bounds.height * 0.5 : view.safeAreaInsets.bottom + 72
        mapView.padding = UIEdgeInsets(top: top, left: 0, bottom: bottom, right: 0)
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
        [kindControl, summaryCard, askButton, spinner, planningOverlay].forEach(view.addSubview)
        NSLayoutConstraint.activate([
            kindControl.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 8),
            kindControl.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
            kindControl.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),

            summaryCard.topAnchor.constraint(equalTo: kindControl.bottomAnchor, constant: 8),
            summaryCard.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
            summaryCard.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),

            askButton.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            askButton.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -16),

            spinner.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            spinner.centerYAnchor.constraint(equalTo: view.centerYAnchor),

            planningOverlay.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            planningOverlay.centerYAnchor.constraint(equalTo: view.centerYAnchor)
        ])
    }

    // MARK: - Browsing categories

    @objc private func kindChanged() {
        agentTripDate = nil
        showSummary(nil)
        let kind = Destination.Kind.browsable[kindControl.selectedSegmentIndex]
        loadDestinations(of: kind)
    }

    private func loadDestinations(of kind: Destination.Kind) {
        searchTask?.cancel() // a newer request always wins over an older, slower one
        setPlanning(false)
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

    // MARK: - Asking the AI agent

    private func showAsk() {
        let ask = AskViewController { [weak self] query, date in
            self?.runAgent(query: query, date: date)
        }
        if let sheet = ask.sheetPresentationController {
            sheet.detents = [.large()]
            sheet.prefersGrabberVisible = true
        }
        let presentAsk: () -> Void = { [weak self] in self?.present(ask, animated: true) }
        if presentedViewController != nil {
            dismiss(animated: true, completion: presentAsk)
        } else {
            presentAsk()
        }
    }

    private func runAgent(query: String, date: Date) {
        searchTask?.cancel()
        spinner.stopAnimating()
        setPlanning(true)
        searchTask = Task { [weak self] in
            guard let self else { return }
            do {
                let origin = try await LocationProvider.shared.currentCoordinate()
                let plan = try await agentService.plan(query: query, from: origin, on: date)
                guard !Task.isCancelled else { return }
                agentTripDate = date
                showAgentPlan(plan)
            } catch {
                guard !Task.isCancelled else { return }
                showRetryAlert(title: "Couldn't plan your trip", message: error.localizedDescription) { [weak self] in self?.runAgent(query: query, date: date) }
            }
            setPlanning(false)
        }
    }

    private func showAgentPlan(_ plan: AgentPlan) {
        let destinations = plan.suggestions.map { suggestion in
            let leaveBy = suggestion.leaveBy.map { "Leave by \($0)." }
            return Destination(
                id: suggestion.placeId,
                name: suggestion.name,
                kind: .suggestion,
                coordinate: CLLocationCoordinate2D(latitude: suggestion.latitude, longitude: suggestion.longitude),
                rating: nil,
                address: nil,
                attributions: nil,
                agentReason: [suggestion.reason, leaveBy].compactMap { $0 }.joined(separator: " ")
            )
        }
        kindControl.selectedSegmentIndex = UISegmentedControl.noSegment // we're showing AI picks, not a category
        showSummary(plan.summary)
        show(destinations, emptyMessage: "The planner couldn't find places that fit. Try describing your trip differently.")
        if let best = destinations.first {
            showDetail(for: best) // open the top pick straight away, with the agent's reason
        }
    }

    private func setPlanning(_ planning: Bool) {
        planningOverlay.isHidden = !planning
        askButton.isEnabled = !planning
        if planning {
            UIAccessibility.post(notification: .announcement, argument: "Planning your trip")
        }
    }

    private func showSummary(_ text: String?) {
        summaryLabel.text = text
        summaryCard.isHidden = (text == nil)
        view.layoutIfNeeded() // the card's height is only known after layout
        updateMapPadding()
    }

    // MARK: - Pins

    private func show(_ destinations: [Destination], emptyMessage: String = "Try another category.") {
        mapView.clear() // removes markers and any route line from before
        routeLine = nil
        guard !destinations.isEmpty else {
            showMessage("No places found", detail: emptyMessage)
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
            tripDate: destination.kind == .suggestion ? agentTripDate : nil,
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
        if let agentReason { return agentReason }
        let ratingText = rating.map { String(format: "★ %.1f", $0) }
        return [ratingText, address].compactMap { $0 }.joined(separator: " · ")
    }
}
