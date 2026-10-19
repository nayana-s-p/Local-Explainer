import AppKit
let directory=CommandLine.arguments[1]
for (size,name) in [(16,"icon_16x16"),(32,"icon_16x16@2x"),(32,"icon_32x32"),(64,"icon_32x32@2x"),(128,"icon_128x128"),(256,"icon_128x128@2x"),(256,"icon_256x256"),(512,"icon_256x256@2x"),(512,"icon_512x512"),(1024,"icon_512x512@2x")] {
 let image=NSImage(size:NSSize(width:size,height:size));image.lockFocus()
 let scale=CGFloat(size)/1024
 let transform=NSAffineTransform();transform.scale(by:scale);transform.concat()
 NSColor(calibratedRed:0.91,green:0.95,blue:0.87,alpha:1).setFill()
 NSBezierPath(roundedRect:NSRect(x:40,y:40,width:944,height:944),xRadius:210,yRadius:210).fill()
 NSColor(calibratedRed:0.19,green:0.43,blue:0.33,alpha:1).setFill()
 NSBezierPath(roundedRect:NSRect(x:210,y:245,width:604,height:495),xRadius:62,yRadius:62).fill()
 NSColor(calibratedRed:0.78,green:0.88,blue:0.7,alpha:1).setFill()
 for i in 0..<5 {let height=CGFloat([110,210,300,180,95][i]);NSBezierPath(roundedRect:NSRect(x:335+CGFloat(i)*75,y:440-height/2,width:40,height:height),xRadius:20,yRadius:20).fill()}
 NSColor(calibratedRed:0.47,green:0.65,blue:0.39,alpha:1).setFill()
 NSBezierPath(roundedRect:NSRect(x:210,y:690,width:604,height:100),xRadius:25,yRadius:25).fill()
 image.unlockFocus()
 let bitmap=NSBitmapImageRep(data:image.tiffRepresentation!)!
 try! bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:directory+"/"+name+".png"))
}
