import UIKit

extension UIViewController {
    /// An error alert that offers to repeat the action, for failures that are often temporary.
    func showRetryAlert(title: String, message: String, retry: @escaping () -> Void) {
        let alert = UIAlertController(title: title, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: "Try Again", style: .default) { _ in retry() })
        alert.preferredAction = alert.actions.last // bold "Try Again", as iOS does for the suggested choice
        present(alert, animated: true)
    }
}
