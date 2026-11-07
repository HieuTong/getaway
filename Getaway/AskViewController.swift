import UIKit

/// A sheet where the user describes the day out they want, in their own words.
final class AskViewController: UIViewController {

    private static let maxLength = 300 // same limit as the backend, so the user can't hit a server error
    private static let examples = [
        "Somewhere cool for a hike, back before dark",
        "A quiet beach for a swim, under 90 minutes away",
        "An easy lookout walk that's good for kids"
    ]

    private let onSubmit: (String, Date) -> Void
    private let textView = UITextView()
    private let placeholderLabel = UILabel()
    private let datePicker = UIDatePicker()
    private var submitButton: UIButton!

    init(onSubmit: @escaping (String, Date) -> Void) {
        self.onSubmit = onSubmit
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemGroupedBackground

        let titleLabel = UILabel()
        titleLabel.text = "Plan a getaway"
        let titleFont = UIFont.preferredFont(forTextStyle: .title2)
        titleLabel.font = UIFont(descriptor: titleFont.fontDescriptor.withSymbolicTraits(.traitBold) ?? titleFont.fontDescriptor,
                                 size: 0)
        titleLabel.adjustsFontForContentSizeCategory = true

        textView.font = .preferredFont(forTextStyle: .body)
        textView.adjustsFontForContentSizeCategory = true
        textView.backgroundColor = .secondarySystemGroupedBackground
        textView.layer.cornerRadius = 12
        textView.layer.cornerCurve = .continuous
        textView.textContainerInset = UIEdgeInsets(top: 12, left: 8, bottom: 12, right: 8)
        textView.delegate = self
        textView.accessibilityLabel = "Describe your trip"

        // UITextView has no built-in placeholder, so we overlay a label and hide it once there's text.
        placeholderLabel.text = "Describe your ideal day out…"
        placeholderLabel.font = .preferredFont(forTextStyle: .body)
        placeholderLabel.textColor = .tertiaryLabel
        placeholderLabel.translatesAutoresizingMaskIntoConstraints = false
        textView.addSubview(placeholderLabel)

        let examplesStack = UIStackView(arrangedSubviews: Self.examples.map { makeExampleButton($0) })
        examplesStack.axis = .vertical
        examplesStack.alignment = .leading
        examplesStack.spacing = 8

        let dateLabel = UILabel()
        dateLabel.text = "Date"
        dateLabel.font = .preferredFont(forTextStyle: .body)
        dateLabel.setContentHuggingPriority(.defaultLow, for: .horizontal) // label stretches, picker stays right
        datePicker.datePickerMode = .date
        datePicker.preferredDatePickerStyle = .compact
        let tomorrow = Calendar.current.date(byAdding: .day, value: 1, to: Calendar.current.startOfDay(for: Date()))!
        datePicker.minimumDate = tomorrow // drive-time predictions need a departure in the future
        datePicker.date = tomorrow
        let dateRow = UIStackView(arrangedSubviews: [dateLabel, datePicker])
        dateRow.alignment = .center

        var submitConfig = UIButton.Configuration.filled()
        submitConfig.title = "Plan my trip"
        submitConfig.image = UIImage(systemName: "sparkles")
        submitConfig.imagePadding = 8
        submitConfig.buttonSize = .large
        submitConfig.cornerStyle = .large
        submitButton = UIButton(configuration: submitConfig, primaryAction: UIAction { [weak self] _ in
            self?.submit()
        })
        submitButton.isEnabled = false

        let stack = UIStackView(arrangedSubviews: [titleLabel, textView, examplesStack, dateRow, submitButton])
        stack.axis = .vertical
        stack.spacing = 16
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)

        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 24),
            stack.leadingAnchor.constraint(equalTo: view.layoutMarginsGuide.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: view.layoutMarginsGuide.trailingAnchor),
            textView.heightAnchor.constraint(equalToConstant: 110),
            placeholderLabel.topAnchor.constraint(equalTo: textView.topAnchor, constant: 12),
            placeholderLabel.leadingAnchor.constraint(equalTo: textView.leadingAnchor, constant: 13)
        ])
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        textView.becomeFirstResponder() // keyboard up straight away: the user came here to type
    }

    private func makeExampleButton(_ text: String) -> UIButton {
        var config = UIButton.Configuration.gray()
        config.title = text
        config.cornerStyle = .capsule
        config.buttonSize = .small
        return UIButton(configuration: config, primaryAction: UIAction { [weak self] _ in
            self?.textView.text = text
            self?.textChanged()
        })
    }

    private func textChanged() {
        let trimmed = textView.text.trimmingCharacters(in: .whitespacesAndNewlines)
        placeholderLabel.isHidden = !textView.text.isEmpty
        submitButton.isEnabled = trimmed.count >= 3 // same minimum as the backend
    }

    private func submit() {
        let query = textView.text.trimmingCharacters(in: .whitespacesAndNewlines)
        let date = datePicker.date
        let onSubmit = onSubmit
        dismiss(animated: true) { onSubmit(query, date) }
    }
}

extension AskViewController: UITextViewDelegate {
    func textViewDidChange(_ textView: UITextView) {
        textChanged()
    }

    // Stop typing at the backend's limit, instead of letting the request fail later.
    func textView(_ textView: UITextView, shouldChangeTextIn range: NSRange, replacementText text: String) -> Bool {
        let current = textView.text as NSString
        return current.replacingCharacters(in: range, with: text).count <= Self.maxLength
    }
}
