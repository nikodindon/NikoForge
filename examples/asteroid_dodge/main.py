import pygame
import sys
import random
from player import Player
from asteroid import Asteroid

# Initialisation Pygame
pygame.init()

# Configuration de l'écran
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Asteroid Dodge - NikoForge")
clock = pygame.time.Clock()

# Couleurs
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)

# Police pour le texte
font = pygame.font.SysFont("arial", 32)
game_over_font = pygame.font.SysFont("arial", 64, bold=True)

def main():
    running = True
    player = Player(WIDTH, HEIGHT)
    asteroids = []
    score = 0
    game_over = False
    spawn_timer = 0
    
    # Boucle principale
    while running:
        # Gestion des événements
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE and game_over:
                    # Redémarrage
                    player = Player(WIDTH, HEIGHT)
                    asteroids = []
                    score = 0
                    game_over = False

        if not game_over:
            keys = pygame.key.get_pressed()
            player.move(keys)

            # Gestion des astéroïdes
            spawn_timer += 1
            if spawn_timer > 30: # Un astéroïde toutes les 30 frames (environ 0.5s)
                asteroids.append(Asteroid(WIDTH))
                spawn_timer = 0

            # Mise à jour et dessin des astéroïdes
            for asteroid in asteroids:
                asteroid.update()
                asteroid.draw(screen)

                # Collision
                if player.rect.colliderect(asteroid.rect):
                    game_over = True
                
                # Suppression si hors écran et augmentation du score
                if asteroid.y > HEIGHT + asteroid.radius:
                    asteroids.remove(asteroid)
                    score += 10

            # Nettoyage de la liste des astéroïdes
            asteroids = [a for a in asteroids if a.y <= HEIGHT + asteroid.radius]

        # Dessin
        screen.fill(BLACK)
        player.draw(screen)

        if not game_over:
            # Affichage du score
            score_text = font.render(f"Score: {score}", True, WHITE)
            screen.blit(score_text, (10, 10))
        else:
            # Affichage Game Over
            text = game_over_font.render("GAME OVER", True, RED)
            text_rect = text.get_rect(center=(WIDTH/2, HEIGHT/2 - 50))
            screen.blit(text, text_rect)
            
            final_score = font.render(f"Score Final: {score}", True, WHITE)
            final_score_rect = final_score.get_rect(center=(WIDTH/2, HEIGHT/2 + 20))
            screen.blit(final_score, final_score_rect)
            
            restart_text = font.render("Appuyez sur ESPACE pour rejouer", True, WHITE)
            restart_rect = restart_text.get_rect(center=(WIDTH/2, HEIGHT/2 + 80))
            screen.blit(restart_text, restart_rect)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()