import UIKit

final class DestinationDetailViewController: UIViewController {

    private enum Section { case leaveTimes }

    // Every row the list can show. Diffable data sources need items to be Hashable.
    private enum Item: Hashable {
        case reason(String)
        case fire(danger: FireDanger?, detail: String)
        case safetyNote(String)
        case loading
        case failed(message: String)
        case summary(String)
        case estimate(departure: Date, duration: TimeInterval, isBest: Bool)
    }

    private let destination: Destination
    private let routesService: RoutesService
    private let onBestRoute: (RouteEstimate) -> Void
    private let onDismiss: () -> Void
    private let tripDate: Date? // the day the user is planning for; nil means tomorrow
    private var loadTask: Task<Void, Never>?

    private var collectionView: UICollectionView!
    private var dataSource: UICollectionViewDiffableDataSource<Section, Item>!

    /// What the AI agent says about this pick: its reason, then bushfire safety. Empty for category results,
    /// because fire data only comes with the agent's plans.
    private var agentItems: [Item] {
        guard destination.kind == .suggestion else { return [] }
        var items: [Item] = []
        if let reason = destination.agentReason { items.append(.reason(reason)) }
        items.append(.fire(danger: destination.fireDanger, detail: fireDetail))
        if let note = destination.safetyNote { items.append(.safetyNote(note)) }
        return items
    }

    /// "Central fire district · Total Fire Ban · Rating: CFA"
    private var fireDetail: String {
        let parts: [String?] = [
            destination.fireDistrict.map { "\($0) fire district" },
            destination.totalFireBan == true ? "Total Fire Ban" : nil,
            "Rating: CFA"
        ]
        return parts.compactMap { $0 }.joined(separator: " · ")
    }

    /// The official action for the rating; unknown is said plainly, never shown as safe.
    private static func fireTitle(for danger: FireDanger?) -> String {
        guard let danger else { return "Fire danger not forecast yet for this date" }
        return danger.action ?? "No fire danger rating issued"
    }

    /// "Leaving tomorrow..." or "Leaving Sat 27 Dec...", matching the day the user is planning for.
    private var leavingHeaderText: String {
        guard let tripDate else { return "Leaving tomorrow from your location" }
        return "Leaving \(Self.dayFormatter.string(from: tripDate)) from your location"
    }

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.timeZone = TimeZone(identifier: "Australia/Melbourne")
        formatter.setLocalizedDateFormatFromTemplate("EEE d MMM") // "Sat 27 Dec", ordered for the user's language
        return formatter
    }()

    // Formatters are expensive to create, so make each one once and reuse it.
    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.timeZone = TimeZone(identifier: "Australia/Melbourne")
        formatter.dateStyle = .none
        formatter.timeStyle = .short
        return formatter
    }()

    private static let durationFormatter: DateComponentsFormatter = {
        let formatter = DateComponentsFormatter()
        formatter.allowedUnits = [.hour, .minute]
        formatter.unitsStyle = .abbreviated
        return formatter
    }()

    init(destination: Destination,
         routesService: RoutesService,
         tripDate: Date? = nil,
         onBestRoute: @escaping (RouteEstimate) -> Void,
         onDismiss: @escaping () -> Void) {
        self.destination = destination
        self.routesService = routesService
        self.tripDate = tripDate
        self.onBestRoute = onBestRoute
        self.onDismiss = onDismiss
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemGroupedBackground

        let header = makeHeader()
        configureCollectionView()
        header.translatesAutoresizingMaskIntoConstraints = false
        collectionView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(header)
        view.addSubview(collectionView)

        NSLayoutConstraint.activate([
            header.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 20),
            // Layout margins line the header up with the list's inset rows below it.
            header.leadingAnchor.constraint(equalTo: view.layoutMarginsGuide.leadingAnchor),
            header.trailingAnchor.constraint(equalTo: view.layoutMarginsGuide.trailingAnchor),
            collectionView.topAnchor.constraint(equalTo: header.bottomAnchor, constant: 4),
            collectionView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            collectionView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            collectionView.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])

        loadEstimates()
    }

    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        loadTask?.cancel() // sheet closed: don't update a screen nobody sees
        onDismiss()
    }

    // MARK: - Header

    private func makeHeader() -> UIView {
        // The kind's symbol on a coloured rounded square, like an Apple Maps place card.
        let icon = UIImageView(image: UIImage(systemName: destination.kind.symbolName))
        icon.tintColor = .white
        icon.preferredSymbolConfiguration = UIImage.SymbolConfiguration(pointSize: 20, weight: .semibold)
        icon.contentMode = .center
        icon.backgroundColor = destination.kind.color
        icon.layer.cornerRadius = 12
        icon.layer.cornerCurve = .continuous // Apple's smooth "squircle" corners
        icon.clipsToBounds = true
        icon.isAccessibilityElement = false // decorative: VoiceOver reads the text instead
        NSLayoutConstraint.activate([
            icon.widthAnchor.constraint(equalToConstant: 48),
            icon.heightAnchor.constraint(equalToConstant: 48)
        ])

        let titleLabel = UILabel()
        titleLabel.text = destination.name
        let titleFont = UIFont.preferredFont(forTextStyle: .title2)
        titleLabel.font = UIFont(descriptor: titleFont.fontDescriptor.withSymbolicTraits(.traitBold) ?? titleFont.fontDescriptor,
                                 size: 0) // size 0 keeps the Dynamic Type size
        titleLabel.adjustsFontForContentSizeCategory = true
        titleLabel.numberOfLines = 2

        let subtitleLabel = UILabel()
        subtitleLabel.attributedText = makeSubtitle()

        let textStack = UIStackView(arrangedSubviews: [titleLabel, subtitleLabel])
        textStack.axis = .vertical
        textStack.spacing = 2

        let closeButton = UIButton(configuration: .plain(), primaryAction: UIAction { [weak self] _ in
            self?.dismiss(animated: true)
        })
        closeButton.configuration?.image = UIImage(systemName: "xmark.circle.fill")
        closeButton.configuration?.preferredSymbolConfigurationForImage =
            UIImage.SymbolConfiguration(pointSize: 26)
                .applying(UIImage.SymbolConfiguration(paletteColors: [.secondaryLabel, .tertiarySystemFill]))
        closeButton.configuration?.contentInsets = .zero
        closeButton.accessibilityLabel = "Close"
        closeButton.setContentHuggingPriority(.required, for: .horizontal)

        let topRow = UIStackView(arrangedSubviews: [icon, textStack, closeButton])
        topRow.spacing = 12
        topRow.alignment = .center

        var start = UIButton.Configuration.filled()
        start.title = "Start"
        start.image = UIImage(systemName: "car.fill")
        start.imagePadding = 8
        start.buttonSize = .large
        start.cornerStyle = .large
        let startButton = UIButton(configuration: start, primaryAction: UIAction { [weak self] _ in
            guard let self else { return }
            GoogleMapsHandoff.openDirections(to: destination) // in-app NavigationViewController needs a billing-enabled project
        })

        var rows: [UIView] = [topRow]
        if destination.kind == .suggestion {
            // The fire danger for this place on the trip date, at a glance, in the rating's own colour.
            let badge = FireDangerBadge(danger: destination.fireDanger, totalFireBan: destination.totalFireBan)
            let badgeRow = UIStackView(arrangedSubviews: [badge])
            badgeRow.axis = .vertical
            badgeRow.alignment = .leading // the pill keeps its natural width instead of stretching across
            rows.append(badgeRow)
        }
        if let address = destination.address {
            let addressLabel = UILabel()
            addressLabel.text = address
            addressLabel.font = .preferredFont(forTextStyle: .subheadline)
            addressLabel.adjustsFontForContentSizeCategory = true
            addressLabel.textColor = .secondaryLabel
            addressLabel.numberOfLines = 2
            rows.append(addressLabel)
        }
        rows.append(startButton)

        let stack = UIStackView(arrangedSubviews: rows)
        stack.axis = .vertical
        stack.spacing = 12
        return stack
    }

    /// "★ 4.7 · Beach", with an orange star SF Symbol inline in the text.
    private func makeSubtitle() -> NSAttributedString {
        let text = NSMutableAttributedString()
        if let rating = destination.rating, let star = UIImage(systemName: "star.fill") {
            let attachment = NSTextAttachment(image: star.withTintColor(.systemOrange, renderingMode: .alwaysOriginal))
            text.append(NSAttributedString(attachment: attachment))
            text.append(NSAttributedString(string: String(format: " %.1f  ·  ", rating)))
        }
        text.append(NSAttributedString(string: destination.kind.singularLabel))
        text.addAttributes([.font: UIFont.preferredFont(forTextStyle: .subheadline),
                            .foregroundColor: UIColor.secondaryLabel],
                           range: NSRange(location: 0, length: text.length))
        return text
    }

    // MARK: - List

    private func configureCollectionView() {
        var config = UICollectionLayoutListConfiguration(appearance: .insetGrouped)
        config.headerMode = .supplementary
        config.footerMode = .supplementary
        config.backgroundColor = .systemGroupedBackground
        collectionView = UICollectionView(frame: .zero,
                                          collectionViewLayout: UICollectionViewCompositionalLayout.list(using: config))
        collectionView.delegate = self

        let cellRegistration = UICollectionView.CellRegistration<UICollectionViewListCell, Item> { cell, _, item in
            var content = UIListContentConfiguration.valueCell() // title left, value right, like Settings
            cell.accessories = []

            switch item {
            case .reason(let text):
                content = .cell()
                content.image = UIImage(systemName: "sparkles")
                content.imageProperties.tintColor = .systemPurple
                content.text = text
                content.textProperties.numberOfLines = 0 // the agent's reason can wrap over several lines

            case .fire(let danger, let detail):
                content = .subtitleCell()
                content.image = UIImage(systemName: "flame.fill")
                content.imageProperties.tintColor = danger?.symbolTint ?? .secondaryLabel
                content.text = Self.fireTitle(for: danger)
                content.textProperties.numberOfLines = 0
                content.secondaryText = detail
                content.secondaryTextProperties.color = .secondaryLabel
                content.secondaryTextProperties.numberOfLines = 0
                cell.accessories = [.disclosureIndicator()] // opens the CFA's ratings page (their feed terms ask for a link)
                cell.accessibilityHint = "Opens the CFA's fire danger ratings page"

            case .safetyNote(let note):
                content = .subtitleCell()
                content.image = UIImage(systemName: "exclamationmark.triangle.fill")
                content.imageProperties.tintColor = .systemOrange
                content.text = note
                content.textProperties.numberOfLines = 0
                content.secondaryText = "Check VicEmergency before you leave"
                content.secondaryTextProperties.color = .link
                cell.accessories = [.disclosureIndicator()]
                cell.accessibilityHint = "Opens VicEmergency"

            case .loading:
                content.text = "Checking traffic…"
                content.textProperties.color = .secondaryLabel
                let spinner = UIActivityIndicatorView(style: .medium)
                spinner.startAnimating()
                cell.accessories = [.customView(configuration: .init(customView: spinner, placement: .trailing()))]

            case .failed(let message):
                content = .subtitleCell()
                content.image = UIImage(systemName: "exclamationmark.triangle.fill")
                content.imageProperties.tintColor = .systemOrange
                content.text = "Couldn't load drive times"
                content.secondaryText = message
                content.secondaryTextProperties.color = .secondaryLabel
                cell.accessories = [.label(text: "Retry")]

            case .summary(let text):
                content = .cell()
                content.image = UIImage(systemName: "lightbulb.fill")
                content.imageProperties.tintColor = .systemYellow
                content.text = text
                content.textProperties.font = .preferredFont(forTextStyle: .headline)

            case .estimate(let departure, let duration, let isBest):
                content.image = UIImage(systemName: isBest ? "star.circle.fill" : "clock")
                content.imageProperties.tintColor = isBest ? .systemGreen : .secondaryLabel
                content.text = Self.timeFormatter.string(from: departure)
                content.secondaryText = Self.durationFormatter.string(from: duration)
                // Same-width digits keep the durations aligned in a neat column.
                let bodySize = UIFont.preferredFont(forTextStyle: .body).pointSize
                content.secondaryTextProperties.font = .monospacedDigitSystemFont(ofSize: bodySize,
                                                                                  weight: isBest ? .semibold : .regular)
                if isBest {
                    content.secondaryTextProperties.color = .systemGreen
                    cell.accessories = [.label(text: "Best")]
                }
            }
            cell.contentConfiguration = content
        }

        let headerText = leavingHeaderText
        let headerRegistration = UICollectionView.SupplementaryRegistration<UICollectionViewListCell>(
            elementKind: UICollectionView.elementKindSectionHeader
        ) { header, _, _ in
            var content = UIListContentConfiguration.groupedHeader()
            content.text = headerText
            header.contentConfiguration = content
        }

        let footerRegistration = UICollectionView.SupplementaryRegistration<UICollectionViewListCell>(
            elementKind: UICollectionView.elementKindSectionFooter
        ) { [weak self] footer, _, _ in
            var content = UIListContentConfiguration.groupedFooter()
            var sources = ["Place data from Google Maps"]
            if let providers = self?.destination.attributions?.string, !providers.isEmpty {
                sources.append(providers)
            }
            if self?.destination.kind == .suggestion {
                sources.append("Fire danger ratings: CFA")
            }
            content.text = sources.joined(separator: " · ")
            footer.contentConfiguration = content
        }

        dataSource = UICollectionViewDiffableDataSource<Section, Item>(collectionView: collectionView) { collectionView, indexPath, item in
            collectionView.dequeueConfiguredReusableCell(using: cellRegistration, for: indexPath, item: item)
        }
        dataSource.supplementaryViewProvider = { collectionView, kind, indexPath in
            kind == UICollectionView.elementKindSectionHeader
                ? collectionView.dequeueConfiguredReusableSupplementary(using: headerRegistration, for: indexPath)
                : collectionView.dequeueConfiguredReusableSupplementary(using: footerRegistration, for: indexPath)
        }
    }

    private func showItems(_ items: [Item]) {
        var snapshot = NSDiffableDataSourceSnapshot<Section, Item>()
        snapshot.appendSections([.leaveTimes])
        snapshot.appendItems(items)
        dataSource.apply(snapshot, animatingDifferences: true)
    }

    // MARK: - Loading

    private func loadEstimates() {
        loadTask?.cancel()
        showItems(agentItems + [.loading])
        loadTask = Task { [weak self] in
            guard let self else { return }
            do {
                let estimates = try await routesService.leaveTimeEstimates(to: destination, on: tripDate)
                guard !Task.isCancelled else { return }
                showEstimates(estimates)
            } catch {
                guard !Task.isCancelled else { return }
                showItems(agentItems + [.failed(message: error.localizedDescription)])
            }
        }
    }

    private func showEstimates(_ estimates: [RouteEstimate]) {
        guard let best = estimates.min(by: { $0.duration < $1.duration }),
              let worst = estimates.max(by: { $0.duration < $1.duration }) else {
            showItems(agentItems + [.failed(message: "Google returned no drive times.")])
            return
        }

        let savedMinutes = Int((worst.duration - best.duration) / 60)
        let bestTime = Self.timeFormatter.string(from: best.departure)
        let summary = savedMinutes > 0 ? "Leave at \(bestTime) to save \(savedMinutes) min"
                                       : "Traffic looks about the same at all these times"

        let rows = estimates.map { estimate in
            Item.estimate(departure: estimate.departure,
                          duration: estimate.duration,
                          isBest: estimate.departure == best.departure)
        }
        showItems(agentItems + [.summary(summary)] + rows)
        onBestRoute(best)
    }
}

// MARK: - UICollectionViewDelegate

extension DestinationDetailViewController: UICollectionViewDelegate {
    // Tappable rows: retry after an error, and the two fire safety links. The rest is information.
    func collectionView(_ collectionView: UICollectionView, shouldSelectItemAt indexPath: IndexPath) -> Bool {
        switch dataSource.itemIdentifier(for: indexPath) {
        case .failed, .fire, .safetyNote: return true
        default: return false
        }
    }

    func collectionView(_ collectionView: UICollectionView, didSelectItemAt indexPath: IndexPath) {
        collectionView.deselectItem(at: indexPath, animated: true)
        switch dataSource.itemIdentifier(for: indexPath) {
        case .failed: loadEstimates()
        case .fire: UIApplication.shared.open(FireSafetyLinks.cfaRatings)
        case .safetyNote: UIApplication.shared.open(FireSafetyLinks.vicEmergency)
        default: break
        }
    }
}
