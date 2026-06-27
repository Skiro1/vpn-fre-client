package main

import (
	"embed"
	"log"

	"github.com/wailsapp/wails/v3/pkg/application"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	app := application.New(application.Options{
		Name:        "Free VPN",
		Description: "Free VPN Client using Cloudflare WARP",
		Services: []application.Service{
			application.NewService(NewVpnService()),
		},
		Assets: application.AssetOptions{
			Handler: application.AssetFileServerFS(assets),
		},
		Mac: application.MacOptions{
			ApplicationShouldTerminateAfterLastWindowClosed: true,
		},
	})

	app.Window.NewWithOptions(application.WebviewWindowOptions{
		Title:         "Free VPN Client",
		Width:         420,
		Height:        760,
		MinWidth:      420,
		MinHeight:     760,
		MaxWidth:      420,
		MaxHeight:     760,
		DisableResize: true,
		BackgroundColour: application.NewRGB(0, 0, 0),
		URL:  "/",
	})

	if err := app.Run(); err != nil {
		log.Fatal(err)
	}
}
