package main

import (
	"bytes"
	"io"
	"log"
	"net/http"
	"os"
)

func proxyHandler(targetURL, apiKey string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		body, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, "Failed to read request body", http.StatusBadRequest)
			return
		}
		defer r.Body.Close()

		req, err := http.NewRequest(http.MethodPost, targetURL, bytes.NewBuffer(body))
		if err != nil {
			http.Error(w, "Failed to create upstream request", http.StatusInternalServerError)
			return
		}

		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("x-api-key", apiKey)

		client := &http.Client{}
		resp, err := client.Do(req)
		if err != nil {
			http.Error(w, "Failed to reach API Gateway", http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body)
	}
}

func main() {
	apiPrediction := os.Getenv("API_PREDICTION")
	apiForecast := os.Getenv("API_FORECAST")
	apiKey := os.Getenv("API_GATEWAY_KEY")
	port := os.Getenv("PORT")
	if port == "" {
		port = "3000"
	}

	// Serve halaman HTML statis
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		http.ServeFile(w, r, "html/index.html")
	})
	http.HandleFunc("/prediction", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "html/prediction.html")
	})
	http.HandleFunc("/forecasting", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "html/forecasting.html")
	})

	// Reverse proxy ke API Gateway
	http.HandleFunc("/api/predict", proxyHandler(apiPrediction, apiKey))
	http.HandleFunc("/api/forecast", proxyHandler(apiForecast, apiKey))

	log.Printf("Server berjalan di port %s...", port)
	log.Fatal(http.ListenAndServe(":"+port, nil))
}
