import Foundation
import ImageIO
import Vision

guard CommandLine.arguments.count > 1 else {
    fputs("usage: macos_ocr image\n", stderr)
    exit(2)
}

let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
      let cgImage = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    fputs("unreadable image\n", stderr)
    exit(2)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["en-US", "hi-IN"]
request.usesLanguageCorrection = true
// Neural Engine builds on this machine raise e5rt error 13. CPU recognition is stable.
request.usesCPUOnly = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    fputs("vision failed: \(error)\n", stderr)
    exit(1)
}

let observations = request.results ?? []
for observation in observations {
    guard let candidate = observation.topCandidates(1).first else { continue }
    let box = observation.boundingBox
    var text = candidate.string
        .replacingOccurrences(of: "\t", with: " ")
        .replacingOccurrences(of: "\n", with: " ")
    if needsIdentifierRepair(text), let repaired = rereadIdentifier(cgImage, box: box) {
        text = repaired
    }
    print(String(
        format: "%.4f\t%.4f\t%.4f\t%.4f\t%.4f\t%@",
        candidate.confidence,
        box.minX,
        box.minY,
        box.maxX,
        box.maxY,
        text
    ))
}

func needsIdentifierRepair(_ text: String) -> Bool {
    text.range(of: "^(PO|INV|GRN)-[0-9]+[^0-9].*$", options: .regularExpression) != nil
}

func rereadIdentifier(_ image: CGImage, box: CGRect) -> String? {
    let pixelWidth = CGFloat(image.width)
    let pixelHeight = CGFloat(image.height)
    var rect = CGRect(
        x: box.minX * pixelWidth,
        y: (1 - box.maxY) * pixelHeight,
        width: max(box.width * pixelWidth, 1),
        height: max(box.height * pixelHeight, 1)
    ).insetBy(dx: -20, dy: -12)
    let bounds = CGRect(x: 0, y: 0, width: pixelWidth, height: pixelHeight)
    rect = rect.intersection(bounds).integral
    guard rect.width > 4, rect.height > 4, let crop = image.cropping(to: rect) else {
        return nil
    }
    let scale: CGFloat = 4
    let scaledWidth = Int(rect.width * scale)
    let scaledHeight = Int(rect.height * scale)
    guard let context = CGContext(
        data: nil,
        width: scaledWidth,
        height: scaledHeight,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
    ) else {
        return nil
    }
    context.interpolationQuality = .high
    context.draw(crop, in: CGRect(x: 0, y: 0, width: scaledWidth, height: scaledHeight))
    guard let scaled = context.makeImage() else {
        return nil
    }

    let again = VNRecognizeTextRequest()
    again.recognitionLevel = .accurate
    again.recognitionLanguages = ["en-US"]
    again.usesLanguageCorrection = false
    again.usesCPUOnly = true
    let handler = VNImageRequestHandler(cgImage: scaled, options: [:])
    guard (try? handler.perform([again])) != nil else {
        return nil
    }
    let joined = (again.results ?? [])
        .compactMap { $0.topCandidates(1).first?.string }
        .joined(separator: " ")
    guard let range = joined.range(of: "(PO|INV|GRN)-[0-9]+", options: .regularExpression) else {
        return nil
    }
    let found = String(joined[range])
    if found.range(of: "^(PO|INV|GRN)-[0-9]+$", options: .regularExpression) != nil {
        return found
    }
    return nil
}
