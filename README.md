# Getaway 🌊🥾

![Backend tests](https://github.com/HieuTong/getaway/actions/workflows/backend-tests.yml/badge.svg)

![Backend tests](https://github.com/HieuTong/getaway/actions/workflows/backend-tests.yml/badge.svg)

**An iOS trip planner for Victorian summer getaways, built on Google Maps Platform.**

Find real beaches, bushwalks and lookouts near Melbourne, see **when to leave** to beat holiday traffic, and get **in-app turn-by-turn navigation** from where you are.

![Getaway demo](docs/demo.gif)

---

## Why this app

Christmas in Melbourne is summer. On Boxing Day the roads to the coast and the hills jam up, and leaving an hour earlier can save a long wait in traffic. Google Maps tells you how long a trip takes if you leave at a given time. Getaway **compares several departure times for you** and recommends the best one.

## Features

- **Real places, live from Google**: beaches, hiking trails and lookouts from the Places SDK (text search, biased to Melbourne), with ratings and addresses.
- **Leave-time comparison**: predicted drive times for four departure slots tomorrow, computed with traffic-aware routing; the fastest slot is highlighted with the minutes it saves.
- **Route preview**: the recommended route is drawn on the map above the detail sheet.
- **In-app turn-by-turn navigation**: Google Navigation SDK with voice guidance, starting from the user's real GPS position.
- **Native iOS design**: bottom sheet with medium/large detents, inset-grouped list, SF Symbols, Dynamic Type, dark mode and VoiceOver labels.

## Tech stack

| Area | Technology |
|---|---|
| Language / UI | Swift, UIKit (programmatic, no storyboards) |
| Maps & navigation | Google Navigation SDK for iOS (includes Maps SDK) |
| Places | Google Places SDK for iOS (`GooglePlacesSwift`, async/await API) |
| Routing | Google Routes API (REST via `URLSession` + `Codable`) |
| Location | Core Location, bridged to async/await |
| Project generation | XcodeGen (`project.yml` is the source of truth) |

## Architecture

~~~
ViewController (map, pins, category control)
 ├── PlacesService      → Places SDK text search, cached per category
 ├── RoutesService      → Routes API, 4 departures fetched in parallel, cached
 │     └── LocationProvider → one-shot GPS fix as an async call
 └── DestinationDetailViewController (bottom sheet)
       └── NavigationViewController (full-screen turn-by-turn)
~~~

UI code never talks to Google directly: services return plain app models (`Destination`, `RouteEstimate`), so data sources can change without touching the screens.

## Engineering decisions

**Concurrency**
- Leave-time requests run in parallel with `withThrowingTaskGroup`: about one request's latency instead of four, and the remaining requests are cancelled automatically if one fails.
- Switching categories cancels the previous search `Task` and checks `Task.isCancelled` before updating the UI, so a slow, stale response can never overwrite newer results.
- Services are `@MainActor` so their caches are only touched on one thread; the network call itself is `nonisolated` so requests run side by side.
- `CLLocationManager`'s delegate callbacks are bridged to a single `async` call with `CheckedContinuation`, and concurrent callers share one GPS request.

**Cost and performance**
- Field masks request only the fields the UI shows, which keeps responses small and billing lower.
- Places results are cached per category; route estimates are cached per destination and an origin rounded to about 1 km, so GPS jitter doesn't trigger new paid calls but a real move does.

**Security**
- API keys live in a gitignored `Secrets.xcconfig`, injected into `Info.plist` at build time; the repository only contains `Secrets.example.xcconfig`.
- The iOS key is restricted to this app's bundle ID and to the specific APIs used; REST calls send the `X-Ios-Bundle-Identifier` header that this restriction requires.

**UI**
- The detail sheet uses `UICollectionLayoutListConfiguration` with a diffable data source; loading, error (tap to retry) and result states are just different snapshots of one `Item` enum.
- Map padding follows the safe area and the sheet height, so camera fitting and the route line always land in the visible part of the map.
- Location permission is "When In Use" plus the location background mode: enough for screen-off guidance without asking for "Always" access.

## Getting started

**Requirements:** Xcode 26 or later, iOS 17+ device or simulator, [XcodeGen](https://github.com/yonaskolb/XcodeGen), and a Google Cloud project with billing enabled.

1. In Google Cloud, enable **Maps SDK for iOS**, **Places API (New)**, **Routes API** and **Navigation SDK**. Create an API key restricted to iOS apps with bundle ID `com.hieutong.getaway`, limited to those APIs.
2. Clone and configure:

~~~bash
git clone https://github.com/HieuTong/getaway.git
cd getaway
cp Secrets.example.xcconfig Secrets.xcconfig
# edit Secrets.xcconfig: set GMS_API_KEY and your DEVELOPMENT_TEAM
brew install xcodegen
xcodegen generate
open Getaway.xcodeproj
~~~

3. Choose a simulator or your iPhone and run. In the Simulator, set a location with **Features → Location → Custom Location…**

> Note: Places, Routes and Navigation calls are billed by Google. Set a budget alert in Cloud console.

## Project structure

~~~
Getaway/
├── AppDelegate.swift / SceneDelegate.swift    App setup, SDK keys, window
├── AppConfig.swift                            Reads build-time config
├── Destination.swift / Destination+UI.swift   Model, and its visual styling
├── PlacesService.swift                        Google Places search
├── RoutesService.swift                        Google Routes API client
├── LocationProvider.swift                     Async current location
├── ViewController.swift                       Map, pins, category control
├── DestinationDetailViewController.swift      Bottom sheet
└── NavigationViewController.swift             Turn-by-turn navigation
project.yml                                    XcodeGen project definition
~~~

## Roadmap

- **AI trip agent**: a FastAPI backend with Gemini tool-calling that turns requests like *"somewhere cool for a hike on Boxing Day, back before dark"* into ranked suggestions, using Places, Routes, weather, fire-danger ratings and sunset times.
- **Day picker**: plan for Christmas Day, Boxing Day or any date.
- **Holiday traffic forecasting**: a graph neural network trained on Victoria's open traffic-signal data.
- **CarPlay**: the navigation experience on the car's screen.

## Author

**Hugh (Hieu) Le**, iOS engineer and Master of AI student at RMIT · [GitHub](https://github.com/HieuTong)
