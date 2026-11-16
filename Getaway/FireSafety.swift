import UIKit

/// A level of the Australian Fire Danger Rating System, spelled as the CFA feed and our backend send it.
enum FireDanger: String, CaseIterable {
    case noRating = "NO RATING"
    case moderate = "MODERATE"
    case high = "HIGH"
    case extreme = "EXTREME"
    case catastrophic = "CATASTROPHIC"

    /// Missing or unexpected values give nil, so they can never crash decoding or look like a safe day.
    init?(apiValue: String?) {
        guard let apiValue, let level = FireDanger(rawValue: apiValue.uppercased()) else { return nil }
        self = level
    }

    var title: String {
        switch self {
        case .noRating: return "No rating"
        case .moderate: return "Moderate"
        case .high: return "High"
        case .extreme: return "Extreme"
        case .catastrophic: return "Catastrophic"
        }
    }

    /// The rating system's official action message for each level.
    var action: String? {
        switch self {
        case .noRating: return nil
        case .moderate: return "Plan and prepare"
        case .high: return "Be ready to act"
        case .extreme: return "Take action now to protect life and property"
        case .catastrophic: return "For your survival, leave bushfire risk areas"
        }
    }

    var isElevated: Bool { rank >= FireDanger.high.rank }

    /// Green, yellow, orange and red, close to the official colours (AFAC's style guide has the exact values).
    var color: UIColor {
        switch self {
        case .noRating: return .systemGray5
        case .moderate: return UIColor(red: 0.39, green: 0.75, blue: 0.19, alpha: 1)
        case .high: return UIColor(red: 1.00, green: 0.89, blue: 0.00, alpha: 1)
        case .extreme: return UIColor(red: 0.97, green: 0.51, blue: 0.00, alpha: 1)
        case .catastrophic: return UIColor(red: 0.68, green: 0.04, blue: 0.04, alpha: 1)
        }
    }

    /// Text that stays readable on each background colour.
    var textColor: UIColor {
        switch self {
        case .noRating: return .label
        case .catastrophic: return .white
        default: return .black
        }
    }

    /// For small icons on a white or dark background, where yellow would be too faint to see.
    var symbolTint: UIColor {
        switch self {
        case .noRating: return .secondaryLabel
        case .moderate: return .systemGreen
        case .high, .extreme: return .systemOrange
        case .catastrophic: return .systemRed
        }
    }

    private var rank: Int {
        switch self {
        case .noRating: return 0
        case .moderate: return 1
        case .high: return 2
        case .extreme: return 3
        case .catastrophic: return 4
        }
    }
}

enum FireSafetyLinks {
    static let vicEmergency = URL(string: "https://emergency.vic.gov.au")!
    static let cfaRatings = URL(string: "https://www.cfa.vic.gov.au/warnings-restrictions/about-fire-danger-ratings")!
}

/// A small coloured pill such as "Fire danger: High · Total Fire Ban".
/// Colour is never the only signal: the level is always written out, and VoiceOver reads it.
final class FireDangerBadge: UIView {

    init(danger: FireDanger?, totalFireBan: Bool?) {
        super.init(frame: .zero)
        let level = danger ?? .noRating
        backgroundColor = level.color
        layer.cornerRadius = 8
        layer.cornerCurve = .continuous
        directionalLayoutMargins = NSDirectionalEdgeInsets(top: 3, leading: 8, bottom: 3, trailing: 8)

        let icon = UIImageView(image: UIImage(systemName: totalFireBan == true ? "flame.fill" : "flame"))
        icon.tintColor = level.textColor
        icon.preferredSymbolConfiguration = UIImage.SymbolConfiguration(textStyle: .caption1, scale: .small)
        icon.setContentHuggingPriority(.required, for: .horizontal)

        let label = UILabel()
        label.text = Self.text(danger: danger, totalFireBan: totalFireBan)
        label.font = .preferredBold(.caption1)
        label.adjustsFontForContentSizeCategory = true
        label.textColor = level.textColor
        label.numberOfLines = 0

        let stack = UIStackView(arrangedSubviews: [icon, label])
        stack.spacing = 4
        stack.alignment = .center
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: layoutMarginsGuide.topAnchor),
            stack.bottomAnchor.constraint(equalTo: layoutMarginsGuide.bottomAnchor),
            stack.leadingAnchor.constraint(equalTo: layoutMarginsGuide.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: layoutMarginsGuide.trailingAnchor)
        ])

        isAccessibilityElement = true
        accessibilityLabel = label.text?.replacingOccurrences(of: " · ", with: ". ")
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    static func text(danger: FireDanger?, totalFireBan: Bool?) -> String {
        var parts = [danger.map { "Fire danger: \($0.title)" } ?? "Fire danger: not forecast yet"]
        if totalFireBan == true { parts.append("Total Fire Ban") }
        return parts.joined(separator: " · ")
    }
}

private extension UIFont {
    /// A bold font that still follows the user's Dynamic Type size.
    static func preferredBold(_ style: UIFont.TextStyle) -> UIFont {
        let base = UIFont.preferredFont(forTextStyle: style)
        return UIFont(descriptor: base.fontDescriptor.withSymbolicTraits(.traitBold) ?? base.fontDescriptor, size: 0)
    }
}
